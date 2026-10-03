"""Module 3 — the background job that notices silent bands.

Until now "band offline" was derived only when a dashboard polled (see
service.sweep_offline_devices): with no dashboard open, a band that died or
lost Wi-Fi raised nothing. This runs the same sweep every
`offline_sweep_interval_seconds`, from the app's lifespan, with its own
database session, so a silent band alerts whether or not anyone is looking.

One process is assumed (the prototype). With several backend instances this
moves to a single scheduled job (PRODUCTION_PLAN.md, C1); the sweep's own
dedupe already keeps a second run from raising a second alert.
"""

import asyncio
import logging

from starlette.concurrency import run_in_threadpool

from app.core.db import SessionLocal
from app.wearables import service

logger = logging.getLogger(__name__)


def sweep_once() -> int:
    db = SessionLocal()
    try:
        return len(service.sweep_offline_devices(db))
    finally:
        db.close()


async def run_offline_sweeper(interval_s: int) -> None:
    while True:
        await asyncio.sleep(interval_s)
        try:
            created = await run_in_threadpool(sweep_once)
            if created:
                logger.info("offline sweep: %d band(s) newly offline", created)
        except Exception:  # keep sweeping: one bad pass must not stop the next
            logger.exception("offline sweep failed")
