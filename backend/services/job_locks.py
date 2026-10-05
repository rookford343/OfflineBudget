"""Module-level locks that serialize the two background jobs most likely to
race themselves: the Mac sleeps through the 5am bank-sync cron, and on wake
APScheduler's `misfire_grace_time` fires the missed cron job in one thread at
the same moment `_scheduler_sweep`'s own interval job notices `bank_sync`
hasn't succeeded today and retries it in another (main.py has the full
writeup). Both threads then call `run_import` at once; each one's duplicate
check only sees committed rows, so both insert the same transactions. The
daily-summary job has the identical shape via the sweep's own retry.

Each job body does a *non-blocking* `acquire()` before doing any real work; a
concurrent caller that finds the lock already held returns immediately
rather than blocking behind (and then redundantly repeating) the run already
in flight.

Living in their own module -- rather than on `backend.main` -- lets
`backend.routers.bank_sync` share `_bank_sync_lock` with the scheduled job
without importing the FastAPI app module from a router.
"""
import threading

_bank_sync_lock = threading.Lock()
_daily_summary_lock = threading.Lock()
