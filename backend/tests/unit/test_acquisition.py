import copy
import threading
from datetime import UTC, datetime
from queue import Queue

from rainstone.acquisition import AcquisitionWorker
from rainstone.adapters.contracts import ObservationBatch


def test_blocked_batch_does_not_pause_kubernetes_or_advance_durable_cursor():
    queue = Queue(maxsize=4)
    blocked, release = threading.Event(), threading.Event()
    durable = {"offset": 0}
    now = [0.0]

    def batch(cursor):
        blocked.set()
        release.wait(2)
        return ObservationBatch(source="gcp_batch", observed_at=datetime.now(UTC), cursor={"offset": 1})

    def kubernetes(cursor):
        # Logical 390-second Batch stall, without a real six-minute test.
        now[0] = 390
        return ObservationBatch(source="kubernetes", observed_at=datetime.now(UTC),
                                cursor={"offset": cursor["offset"] + 1})

    cloud = AcquisitionWorker("gcp_batch", batch, queue, cursor=durable,
                              interval=1, backoff=lambda _: 1, clock=lambda: now[0])
    watch = AcquisitionWorker("kubernetes", kubernetes, queue, cursor=durable,
                              interval=1, backoff=lambda _: 1, clock=lambda: now[0], continuous=True)
    cloud.start()
    assert blocked.wait(1)
    watch.start()
    try:
        for expected in range(1, 4):
            delivery = queue.get(timeout=1)
            assert delivery.source == "kubernetes"
            assert delivery.payload.cursor["offset"] == expected
        assert durable == {"offset": 0}
        assert not cloud.stalled(now[0], 450)
        assert cloud.stalled(now[0], 180)
    finally:
        cloud.stop()
        watch.stop()
        release.set()
        cloud.thread.join(1)
        watch.thread.join(1)


def test_queue_saturation_is_bounded_and_stop_interrupts_backpressure():
    queue = Queue(maxsize=1)
    second = threading.Event()
    calls = []

    def acquire(cursor):
        calls.append(copy.deepcopy(cursor))
        if len(calls) == 2:
            second.set()
        return ObservationBatch(source="kubernetes", observed_at=datetime.now(UTC),
                                cursor={"offset": cursor.get("offset", 0) + 1})

    now = [0.0]
    worker = AcquisitionWorker("kubernetes", acquire, queue, cursor={}, interval=0, backoff=lambda _: 0,
                               clock=lambda: now[0])
    worker.start()
    try:
        assert second.wait(1)
        assert queue.qsize() == 1
        assert len(calls) == 2
        assert worker.cursor == {"offset": 1}
        # Backpressure from a slow writer is not a stalled acquisition.
        for _ in range(100):
            if worker.phase == "queueing":
                break
            threading.Event().wait(0.01)
        now[0] = 1000
        assert not worker.stalled(now[0], 180)
    finally:
        worker.stop()
        worker.thread.join(1)
    assert not worker.thread.is_alive()


def test_worker_retries_failed_acquisition_from_unchanged_cursor():
    queue = Queue(maxsize=2)
    calls = []

    def acquire(cursor):
        calls.append(copy.deepcopy(cursor))
        cursor["nested"]["value"] = 99
        if len(calls) == 1:
            raise RuntimeError("temporary")
        return ObservationBatch(source="gcp_batch", observed_at=datetime.now(UTC), cursor=cursor)

    worker = AcquisitionWorker("gcp_batch", acquire, queue, cursor={"nested": {"value": 1}},
                               interval=100, backoff=lambda _: 0)
    worker.start()
    try:
        failed = queue.get(timeout=1)
        assert isinstance(failed.error, RuntimeError)
        assert failed.retry_seconds == 0
        assert queue.get(timeout=1).error is None
        # A failed adapter may mutate its input; it cannot mutate the worker's
        # last successfully delivered cursor.
        assert [item["nested"]["value"] for item in calls] == [1, 1]
    finally:
        worker.stop()
        worker.thread.join(1)
