"""Unit tests for the in-app periodic scheduler (buddle.core.scheduler).

No DB needed: jobs are plain coroutines and Redis is fakeredis, so these run
in the fast (non-skipped) suite. What we pin down:

* a job runs repeatedly at its interval,
* the Redis NX lock makes runs exclusive across scheduler instances
  (multi-replica safety),
* a raising job is counted as an error and the loop survives,
* stop() cancels cleanly,
* metrics counters receive the right (job, outcome) labels.
"""

from __future__ import annotations

import asyncio
from typing import Any

import fakeredis.aioredis
import pytest

from buddle.core import metrics
from buddle.core.scheduler import PeriodicJob, Scheduler


@pytest.fixture
def fake_redis() -> Any:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


async def _wait_until(cond, timeout: float = 2.0, step: float = 0.01) -> None:
    """Poll `cond()` until truthy or fail the test after `timeout` seconds."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if cond():
            return
        await asyncio.sleep(step)
    raise AssertionError("condition not met within timeout")


class _CountingMetric:
    """Drop-in for the metrics counters: records (labels) -> count."""

    def __init__(self) -> None:
        self.counts: dict[tuple[tuple[str, str], ...], float] = {}
        self._pending: tuple[tuple[str, str], ...] = ()

    def labels(self, **kw: str) -> _CountingMetric:
        self._pending = tuple(sorted(kw.items()))
        return self

    def inc(self, amount: float = 1) -> None:
        self.counts[self._pending] = self.counts.get(self._pending, 0) + amount

    def observe(self, amount: float) -> None:  # histogram shim
        self.inc(amount)

    def get(self, **kw: str) -> float:
        return self.counts.get(tuple(sorted(kw.items())), 0)


@pytest.fixture
def capture_metrics(monkeypatch: pytest.MonkeyPatch) -> dict[str, _CountingMetric]:
    runs = _CountingMetric()
    dur = _CountingMetric()
    monkeypatch.setattr(metrics, "scheduler_runs_total", runs)
    monkeypatch.setattr(metrics, "scheduler_run_duration", dur)
    return {"runs": runs, "duration": dur}


async def test_job_runs_periodically(fake_redis: Any, capture_metrics: dict) -> None:
    hits = 0

    async def job() -> dict[str, int]:
        nonlocal hits
        hits += 1
        return {"hits": hits}

    # interval_s=1이지만 락 TTL(=interval*0.9)을 피하려 매 사이클 전 락을 비워
    # 짧은 벽시계 안에 2회 이상 실행을 관찰한다 → 대신 interval을 줄일 수 없는
    # 정수 제약이 있으므로 0초 sleep을 위해 monkeypatch 대신 직접 _run_once 사용.
    sched = Scheduler(fake_redis, [PeriodicJob("k", 1, job, max_initial_jitter_s=0)])
    sched.start()
    try:
        await _wait_until(lambda: hits >= 2, timeout=3.5)
    finally:
        await sched.stop()

    assert hits >= 2
    assert capture_metrics["runs"].get(job="k", outcome="ok") >= 2


async def test_lock_excludes_concurrent_instances(fake_redis: Any, capture_metrics: dict) -> None:
    """두 스케줄러 인스턴스(=두 레플리카)가 같은 잡을 들고 있어도, 한 인터벌에
    실제 실행은 정확히 한 번이고 나머지는 skipped_lock으로 집계된다."""
    ran: list[str] = []

    def make(tag: str) -> PeriodicJob:
        async def job() -> None:
            ran.append(tag)

        return PeriodicJob("excl", 60, job, max_initial_jitter_s=0)

    a = Scheduler(fake_redis, [make("a")])
    b = Scheduler(fake_redis, [make("b")])

    # 같은 사이클을 손으로 한 번씩 — 락 NX 의미만 검증 (interval 대기 불필요).
    await a._run_once(a._jobs[0])
    await b._run_once(b._jobs[0])

    assert len(ran) == 1  # 한 쪽만 실행
    runs = capture_metrics["runs"]
    assert runs.get(job="excl", outcome="ok") == 1
    assert runs.get(job="excl", outcome="skipped_lock") == 1


async def test_error_is_isolated_and_counted(fake_redis: Any, capture_metrics: dict) -> None:
    boom_then_ok = {"n": 0}

    async def job() -> None:
        boom_then_ok["n"] += 1
        if boom_then_ok["n"] == 1:
            raise RuntimeError("sweep failed")

    j = PeriodicJob("flaky", 60, job, max_initial_jitter_s=0)
    sched = Scheduler(fake_redis, [j])

    await sched._run_once(j)            # 1회차: 예외 → error 집계, 전파 없음
    await fake_redis.delete("buddle:sched:lock:flaky")
    await sched._run_once(j)            # 2회차: 정상

    runs = capture_metrics["runs"]
    assert runs.get(job="flaky", outcome="error") == 1
    assert runs.get(job="flaky", outcome="ok") == 1
    assert j.runs == 1                  # 성공 실행만 카운트


async def test_stop_cancels_cleanly(fake_redis: Any, capture_metrics: dict) -> None:
    started = asyncio.Event()

    async def job() -> None:
        started.set()
        await asyncio.sleep(0.05)

    sched = Scheduler(fake_redis, [PeriodicJob("stoppable", 1, job, max_initial_jitter_s=0)])
    sched.start()
    await started.wait()
    await sched.stop()
    assert sched._tasks == []           # 태스크 정리 완료

    # stop() 이후 추가 실행 없음을 잠깐 관찰
    before = capture_metrics["runs"].get(job="stoppable", outcome="ok")
    await asyncio.sleep(0.15)
    after = capture_metrics["runs"].get(job="stoppable", outcome="ok")
    assert after == before


async def test_redis_lock_failure_skips_cycle(capture_metrics: dict) -> None:
    """Redis가 죽어도 사이클은 건너뛸 뿐 루프/앱은 죽지 않는다."""

    class BrokenRedis:
        async def set(self, *a: Any, **kw: Any) -> bool:
            raise ConnectionError("redis down")

    ran = False

    async def job() -> None:
        nonlocal ran
        ran = True

    j = PeriodicJob("nolock", 60, job, max_initial_jitter_s=0)
    sched = Scheduler(BrokenRedis(), [j])  # type: ignore[arg-type]
    await sched._run_once(j)

    assert ran is False
    assert capture_metrics["runs"].get(job="nolock", outcome="skipped_lock") == 1
