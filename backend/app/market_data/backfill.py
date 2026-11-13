"""Non-blocking, resumable broker historical data backfill.

A broker's own terminal may display a different historical depth from its public API.
We walk backward to the *documented API floor*, never invent candles, and report
broker-imposed failures instead of claiming those older prices exist.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.brokers.base import AuthError, RateLimitError
from app.market_data.history import sync_history,window_days

IST = ZoneInfo('Asia/Kolkata')


def earliest_api_date(broker_id: str, interval: str, now: datetime | None = None) -> datetime:
    """Oldest date worth probing, based on public API documentation, not chart UI.

    For providers with no published hard floor, the date is a search boundary,
    NOT a promise that the broker will return candles that far back. Users may
    override the boundary using HISTORY_EARLIEST_<BROKER>_(INTRADAY|DAILY).
    """
    now = now or datetime.now(IST)
    intraday = interval.endswith(('m', 'h'))
    group = 'INTRADAY' if intraday else 'DAILY'
    override = os.getenv(f'HISTORY_EARLIEST_{broker_id.upper()}_{group}')
    if override:
        parsed = datetime.fromisoformat(override)
        return parsed.replace(tzinfo=IST) if parsed.tzinfo is None else parsed.astimezone(IST)
    if broker_id == 'upstox': year, month, day = (2022, 1, 1) if intraday else (2000, 1, 1)
    elif broker_id == 'groww': year, month, day = 2020, 1, 1
    elif broker_id == 'fyers': year, month, day = (2017, 7, 3) if intraday else (2000, 1, 1)
    elif broker_id == 'zerodha': year, month, day = (2015, 1, 1) if intraday else (2000, 1, 1)
    else: year, month, day = (2015, 1, 1) if intraday else (2000, 1, 1)
    return min(now, datetime(year, month, day, tzinfo=IST))


@dataclass
class BackfillState:
    account: str
    instrument: Any
    interval: str
    status: str = 'queued'
    oldest_target: str = ''
    scanned_until: str = ''
    oldest_cached: str | None = None
    fetched_pages: int = 0
    pages_scanned: int = 0
    bars_saved: int = 0
    error: str = ''
    note: str = ''
    _task: asyncio.Task | None = field(default=None, repr=False)

    def public(self) -> dict:
        return {k: getattr(self, k) for k in (
            'account', 'interval', 'status', 'oldest_target', 'scanned_until',
            'oldest_cached', 'fetched_pages', 'pages_scanned', 'bars_saved',
            'error', 'note')}


class BackfillManager:
    """One queued task per account/instrument/timeframe; one broker request at a time.

    Coverage records and candles reside in SQLite, so restarting the backend resumes
    a completed range without downloading it again. Tasks themselves are ephemeral.
    """

    def __init__(self, sessions: dict, store: Any):
        self.sessions, self.store = sessions, store
        self.jobs: dict[tuple, BackfillState] = {}
        self.locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def key(account, instrument, interval) -> tuple:
        return (account, instrument.exchange, instrument.symbol, instrument.segment, interval)

    def status(self, account, instrument, interval):
        job = self.jobs.get(self.key(account, instrument, interval))
        if job: return job.public()
        cached = self.store.oldest_candle(account, instrument, interval)
        return {'account':account, 'interval':interval, 'status':'not_started',
                'oldest_target':'', 'scanned_until':'', 'oldest_cached':cached,
                'fetched_pages':0, 'pages_scanned':0, 'bars_saved':0,
                'error':'', 'note':'History is stored locally. Start full backfill to retrieve earlier API candles.'}

    def start(self, account, instrument, interval, adapter=None):
        job_key = self.key(account, instrument, interval)
        previous = self.jobs.get(job_key)
        if previous and previous._task and not previous._task.done():return previous.public()
        if previous and previous.status=='complete':return previous.public()
        if adapter is None: adapter = self.sessions[account]
        floor = earliest_api_date(adapter.broker_id, interval)
        job = BackfillState(account, instrument, interval, oldest_target=floor.isoformat(),
            oldest_cached=self.store.oldest_candle(account, instrument, interval),
            note='API history may differ from the broker terminal and depends on the account plan, instrument listing and contract expiry.')
        self.jobs[job_key] = job
        job._task = asyncio.create_task(self._run(job, adapter, floor))
        return job.public()

    async def _run(self, job: BackfillState, adapter, floor: datetime):
        job.status = 'running'
        lock = self.locks.setdefault(job.account, asyncio.Lock())
        # Stable date boundary makes previous coverage reusable across restarts.
        # Today's partial candles are handled separately by the recent refresh.
        cursor = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
        step = timedelta(days=window_days(adapter.broker_id, job.interval))
        try:
            # Do not call an unknown broker forever. An instrument listed after the
            # earliest-api date may simply produce empty responses before listing.
            max_pages = 2000
            consecutive_empty = 0
            while cursor > floor and job.pages_scanned < max_pages:
                if self.sessions.get(job.account) is not adapter:
                    job.status='paused';job.error='Broker session changed or disconnected. Reconnect to continue.';return
                begin = max(floor, cursor-step)
                # Successful pages are tracked in history_coverage and skipped on resume.
                before = self.store.oldest_candle(job.account, job.instrument, job.interval)
                retries = 0
                while True:
                    try:
                        async with lock:
                            calls = await sync_history(adapter, job.account, job.instrument, job.interval,
                                                       begin, cursor, self.store, max_batches=3)
                        break
                    except RateLimitError as exc:
                        retries += 1
                        if retries > 4:raise
                        await asyncio.sleep(min(30, max(1.0, exc.retry_after or 2**retries)))
                    except AuthError:
                        raise
                job.fetched_pages += calls
                job.pages_scanned += 1
                newest_oldest = self.store.oldest_candle(job.account, job.instrument, job.interval)
                job.oldest_cached = newest_oldest
                job.scanned_until = begin.isoformat()
                if calls == 0:
                    # Previously fetched/cached window; it says nothing about
                    # broker retention and must not count as an empty response.
                    consecutive_empty = 0
                elif newest_oldest and newest_oldest != before:
                    consecutive_empty = 0
                else:
                    consecutive_empty += 1
                cursor = begin
                # For Upstox and Groww we have documented historical availability
                # boundaries. Other providers often expose smaller account-specific
                # windows; halt after many empty pages and report the limitation.
                if adapter.broker_id not in ('upstox','groww') and consecutive_empty >= 12:
                    job.status = 'partial'
                    job.note='Stopped after 12 empty windows; API history may be shorter than the broker terminal. Set HISTORY_EARLIEST_<BROKER>_<INTRADAY|DAILY> to probe a different start date.'
                    return
                if cursor > floor:
                    if calls:await asyncio.sleep(.35)
            job.status = 'complete' if cursor <= floor else 'partial'
            if job.status == 'partial':job.note='Safety request cap reached; restart the backfill to continue.'
            else:job.note='Scanned to the documented API history boundary. Actual oldest candle depends on the instrument and API entitlement.'
        except asyncio.CancelledError:
            job.status='paused';job.error='Backfill interrupted. Start it again to resume from cached windows.'
            raise
        except Exception as exc:
            job.status='paused' if isinstance(exc, AuthError) else 'partial'
            job.error=f'{type(exc).__name__}: {str(exc)[:300]}'
            job.note='Earlier candles were kept. Reconnect or restart the backfill after resolving the broker/API error.'

    async def stop_all(self):
        tasks = [j._task for j in self.jobs.values() if j._task and not j._task.done()]
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
