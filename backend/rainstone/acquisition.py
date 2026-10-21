"""Bounded, replayable acquisition without database writes."""

import copy
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from queue import Full, Queue
from typing import Any

from rainstone.adapters.contracts import ObservationBatch


@dataclass(frozen=True)
class Delivery:
    source: str
    started_at: float
    completed_at: float
    payload: Any = None
    error: Exception | None = None
    retry_seconds: float | None = None


class AcquisitionWorker:
    """One source owns its speculative cursor; only the coordinator persists it."""

    def __init__(
        self, source: str, acquire: Callable[[dict], Any], queue: Queue,
        *, cursor: dict, interval: float, backoff: Callable[[int], float],
        clock: Callable[[], float] = time.monotonic, continuous: bool = False,
    ) -> None:
        self.source, self.acquire, self.queue = source, acquire, queue
        self.cursor = copy.deepcopy(cursor)
        self.interval, self.backoff, self.clock = interval, backoff, clock
        self.continuous = continuous
        self.stopping = threading.Event()
        self.phase = "starting"
        self.progress_at = clock()
        self.thread = threading.Thread(target=self._run, name=f"collect-{source}", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()

    def stalled(self, now: float, deadline: float) -> bool:
        # Waiting on a full queue is backpressure from a slow writer, which the
        # coordinator's own heartbeat already covers.
        return (not self.thread.is_alive() or
                (self.phase == "acquiring" and now - self.progress_at > deadline))

    def _run(self) -> None:
        failures = 0
        while not self.stopping.is_set():
            self.progress_at = self.clock()
            self.phase = "acquiring"
            started = self.progress_at
            try:
                payload = self.acquire(copy.deepcopy(self.cursor))
                delivery = Delivery(self.source, started, self.clock(), payload=payload)
                failures = 0
                delay = self.interval
                if isinstance(payload, ObservationBatch):
                    delay = 0 if self.continuous or not payload.exhausted else delay
            except Exception as error:  # noqa: BLE001 - coordinator records source failures
                failures += 1
                delay = self.backoff(failures)
                delivery = Delivery(self.source, started, self.clock(), error=error, retry_seconds=delay)
            self.progress_at = self.clock()
            self.phase = "queueing"
            while not self.stopping.is_set():
                try:
                    self.queue.put(delivery, timeout=0.1)
                    break
                except Full:
                    continue
            else:
                return
            if isinstance(delivery.payload, ObservationBatch):
                # Replay after process loss starts from the coordinator's durable
                # cursor, never this in-memory cursor ahead of queued batches.
                self.cursor = copy.deepcopy(delivery.payload.cursor)
            self.phase = "waiting"
            if self.stopping.wait(delay):
                return
