"""In-app periodic scheduler for standby ticks (knowledge / plaza).

Design notes
------------
The tick *functions* already exist as bounded one-sweep coroutines that commit
their own work (`knowledge_service.knowledge_tick`, `plaza_service.tick`) and
are exposed on admin endpoints for external cron. This module adds the missing
piece from the roadmap: the app can drive those sweeps itself, so a single
``docker compose up`` produces a living plaza without any crontab.

Properties:

* **Opt-in.** ``Settings.scheduler_enabled`` defaults to ``False`` — tests,
  scripts and ad-hoc shells never spawn background loops. Admin tick endpoints
  keep working regardless, so external cron stays a first-class alternative.
* **Multi-replica safe.** Each cycle first takes a Redis ``SET NX EX`` lock
  (``buddle:sched:lock:{job}``). With N replicas, exactly one runs the sweep
  per interval; the rest record ``skipped_lock`` and sleep. The lock TTL is
  ~90% of the interval so a crashed holder can never wedge the schedule for
  more than one period, and we deliberately *don't* release the lock on
  success — holding it until expiry is what enforces "once per interval
  across the fleet".
* **Crash-isolated.** A failing sweep is logged + counted and the loop keeps
  going; an unexpected error in the loop machinery itself backs off one
  interval instead of dying.
* **Session-per-run.** Every cycle opens a fresh ``AsyncSessionLocal`` so a
  poisoned session can't leak across runs; the tick functions commit
  internally, and we roll back defensively on error.
* **Graceful shutdown.** ``stop()`` cancels the tasks and awaits them, so
  lifespan teardown leaves no orphan loops.
* **Jittered start.** Each job sleeps ``random.uniform(0, min(interval, 5))``
  before its first cycle so replicas booted together don't stampede Redis/DB.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from buddle.core import metrics
from buddle.core.logging import get_logger
from buddle.core.types import RedisClient

log = get_logger(__name__)

_LOCK_PREFIX = "buddle:sched:lock:"
# Lock lives slightly shorter than the interval: guarantees at-most-one run
# per interval across replicas, while a dead holder frees the slot by TTL.
_LOCK_TTL_RATIO = 0.9
_MIN_LOCK_TTL_S = 1


JobFn = Callable[[], Awaitable[object]]


@dataclass
class PeriodicJob:
    """One named coroutine executed every ``interval_s`` seconds."""

    name: str
    interval_s: int
    fn: JobFn
    # Test hook: shrink the initial jitter window (default ≤5 s).
    max_initial_jitter_s: float = 5.0
    _runs: int = field(default=0, init=False)

    @property
    def runs(self) -> int:
        return self._runs

    def _mark_run(self) -> None:
        self._runs += 1


class Scheduler:
    """Drives a set of :class:`PeriodicJob` loops with Redis-lock leadership."""

    def __init__(self, redis_client: RedisClient, jobs: list[PeriodicJob]) -> None:
        self._redis = redis_client
        self._jobs = jobs
        self._tasks: list[asyncio.Task[None]] = []
        self._instance_id = uuid.uuid4().hex  # lock value, for debuggability
        self._stopping = asyncio.Event()

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._tasks:  # idempotent
            return
        for job in self._jobs:
            self._tasks.append(asyncio.create_task(self._loop(job), name=f"sched:{job.name}"))
        log.info("scheduler.started", jobs=[j.name for j in self._jobs])

    async def stop(self) -> None:
        self._stopping.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        log.info("scheduler.stopped")

    # ── internals ──────────────────────────────────────────────────────────

    async def _acquire(self, job: PeriodicJob) -> bool:
        ttl = max(_MIN_LOCK_TTL_S, int(job.interval_s * _LOCK_TTL_RATIO))
        try:
            ok = await self._redis.set(
                _LOCK_PREFIX + job.name, self._instance_id, nx=True, ex=ttl
            )
            return bool(ok)
        except Exception as e:  # Redis hiccup → skip this cycle, never crash
            log.warning("scheduler.lock_error", job=job.name, error=str(e))
            return False

    async def _run_once(self, job: PeriodicJob) -> None:
        if not await self._acquire(job):
            metrics.scheduler_runs_total.labels(job=job.name, outcome="skipped_lock").inc()
            return
        start = time.perf_counter()
        try:
            result = await job.fn()
            duration = time.perf_counter() - start
            metrics.scheduler_runs_total.labels(job=job.name, outcome="ok").inc()
            metrics.scheduler_run_duration.labels(job=job.name).observe(duration)
            job._mark_run()
            log.info(
                "scheduler.run_ok",
                job=job.name,
                duration_ms=round(duration * 1000, 1),
                result=result if isinstance(result, dict) else None,
            )
        except Exception as e:
            metrics.scheduler_runs_total.labels(job=job.name, outcome="error").inc()
            log.warning("scheduler.run_error", job=job.name, error=str(e))

    async def _loop(self, job: PeriodicJob) -> None:
        # Jitter the first cycle so co-booted replicas don't stampede.
        jitter = random.uniform(0, min(job.interval_s, job.max_initial_jitter_s))
        try:
            await asyncio.sleep(jitter)
            while not self._stopping.is_set():
                await self._run_once(job)
                await asyncio.sleep(job.interval_s)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # loop machinery itself failed — back off, retry
            log.error("scheduler.loop_error", job=job.name, error=str(e))
            await asyncio.sleep(job.interval_s)


# ── App-facing factory ───────────────────────────────────────────────────────


def build_default_scheduler(redis_client: RedisClient) -> Scheduler:
    """Wire the two standby sweeps onto a scheduler.

    Imports are local so importing this module stays cheap and cycle-free;
    each run opens its own DB session (tick functions commit internally).
    """
    from buddle.config import get_settings
    from buddle.db.session import AsyncSessionLocal

    settings = get_settings()

    async def _knowledge_tick() -> object:
        from buddle.services import knowledge_service

        async with AsyncSessionLocal() as db:
            try:
                return await knowledge_service.knowledge_tick(db)
            except Exception:
                await db.rollback()
                raise

    async def _plaza_tick() -> object:
        from buddle.services import plaza_service

        async with AsyncSessionLocal() as db:
            try:
                return await plaza_service.tick(db, redis_client=redis_client)
            except Exception:
                await db.rollback()
                raise

    async def _news_tick() -> object:
        from buddle.services.news_service import news_tick

        async with AsyncSessionLocal() as db:
            try:
                return await news_tick(db, redis=redis_client)
            except Exception:
                await db.rollback()
                raise

    jobs = [
        PeriodicJob("knowledge_tick", settings.knowledge_tick_interval_s, _knowledge_tick),
        PeriodicJob("plaza_tick", settings.plaza_tick_interval_s, _plaza_tick),
        PeriodicJob("news_tick", settings.news_tick_interval_s, _news_tick),
    ]
    return Scheduler(redis_client, jobs)
