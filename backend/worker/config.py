"""Worker tuning constants, env-overridable for tests (a short lease/poll
interval makes lease-expiry tests fast) and for production tuning without a
code change -- same pattern as BackendConfig.from_env()."""

import os

# How long a claim is valid before another worker may treat it as
# abandoned. Must comfortably exceed HEARTBEAT_INTERVAL_SECONDS -- the
# worker renews well before expiry, so this is a safety margin for a
# stalled (not dead) worker, not the expected renewal cadence.
LEASE_SECONDS = float(os.environ.get("WORKER_LEASE_SECONDS", "120"))

# How often a worker extends its own lease while running a job. A fraction
# of LEASE_SECONDS so a single missed heartbeat (a slow DB write, a GC
# pause) doesn't let the lease expire before the next attempt.
HEARTBEAT_INTERVAL_SECONDS = float(os.environ.get("WORKER_HEARTBEAT_SECONDS", "30"))

# How long a worker sleeps between claim attempts when the queue is empty.
POLL_INTERVAL_SECONDS = float(os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "1.0"))

# Failed attempts (explicit exception, or an abandoned/expired-lease
# reclaim) allowed before a job is moved to the terminal DEAD_LETTER status
# instead of being requeued again.
MAX_RETRIES = int(os.environ.get("WORKER_MAX_RETRIES", "3"))
