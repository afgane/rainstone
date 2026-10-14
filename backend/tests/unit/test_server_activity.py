from datetime import UTC, datetime, timedelta

from rainstone.server_activity import concurrency, merge_windows, peak_buckets

START = datetime(2026, 10, 1, tzinfo=UTC)


def window(job: str, left: int, right: int) -> dict:
    return {
        "job_id": job, "source_id": job, "from": START + timedelta(minutes=left),
        "to": START + timedelta(minutes=right), "running": False,
    }


def test_overlapping_attempts_are_one_job_but_retry_waits_are_not_execution() -> None:
    intervals = merge_windows([
        window("one", 0, 10), window("one", 5, 20), window("one", 25, 30), window("two", 10, 25),
    ])
    assert [(row["job_id"], row["from"], row["to"]) for row in intervals] == [
        ("one", START, START + timedelta(minutes=20)),
        ("two", START + timedelta(minutes=10), START + timedelta(minutes=25)),
        ("one", START + timedelta(minutes=25), START + timedelta(minutes=30)),
    ]
    steps = concurrency(intervals, START, START + timedelta(minutes=40))
    assert [(int((row["from"] - START).total_seconds() / 60),
             int((row["to"] - START).total_seconds() / 60), row["count"]) for row in steps] == [
        (0, 10, 1), (10, 20, 2), (20, 30, 1), (30, 40, 0),
    ]


def test_an_empty_session_has_no_invented_activity() -> None:
    assert concurrency([], START, START + timedelta(hours=1)) == [
        {"from": START, "to": START + timedelta(hours=1), "count": 0},
    ]


def test_dense_buckets_preserve_brief_peaks_and_half_open_boundaries(monkeypatch) -> None:
    from rainstone import server_activity

    monkeypatch.setattr(server_activity, "MAX_BUCKETS", 4)
    end = START + timedelta(minutes=40)
    steps = concurrency([
        window("first", 0, 10), window("second", 10, 20),
        window("burst", 11, 12), window("last", 30, 40),
    ], START, end)
    buckets = peak_buckets(steps, START, end)
    assert [row["count"] for row in buckets] == [1, 2, 0, 1]
    assert buckets[0]["from"] == START
    assert buckets[-1]["to"] == end
    assert all(left["to"] == right["from"] for left, right in zip(buckets, buckets[1:], strict=False))
