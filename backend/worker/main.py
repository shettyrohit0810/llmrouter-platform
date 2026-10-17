"""Standalone worker process entrypoint: `python -m backend.worker.main`.

Polls the jobs table, claims and runs one job at a time (this process's
single thread only ever executes one job at once -- run multiple worker
containers/processes for concurrency; see docker-compose.yml's `worker`
service and `docker compose up --scale worker=N`), and loops until told to
stop.

SIGTERM triggers a graceful stop after the current job finishes. SIGKILL
(`docker kill -s KILL`, or a hard crash) can't be intercepted at all --
that abrupt, no-warning death is exactly the case backend/worker/queue.py's
lease-expiry mechanism exists to recover from: the job stays claimed until
its lease runs out, then any other worker treats it as reclaimable.
"""

import logging
import os
import signal
import socket
import time
from types import FrameType
from typing import Optional

from backend.api.middleware.logging_context import configure_logging
from backend.config import BackendConfig
from backend.db.session import init_engine, session_scope
from backend.worker.config import POLL_INTERVAL_SECONDS
from backend.worker.queue import claim_next_job
from backend.worker.runner import run_claimed_job

logger = logging.getLogger("backend.worker.main")

_shutdown_requested = False


def _handle_shutdown_signal(signum: int, frame: Optional[FrameType]) -> None:
    global _shutdown_requested
    logger.info("Received signal %s -- will stop after the current job finishes", signum)
    _shutdown_requested = True


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def run_forever() -> None:
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)

    config = BackendConfig.from_env()
    configure_logging(config.log_level)
    init_engine(config.database_url)

    # Router inference/training use PyTorch, which by default spawns one thread per core in
    # *every* process. N workers on one machine then oversubscribe the CPU and run slower
    # than one. Cap each worker's threads (about cores / workers) with WORKER_TORCH_THREADS.
    torch_threads = os.environ.get("WORKER_TORCH_THREADS")
    if torch_threads:
        import torch

        torch.set_num_threads(int(torch_threads))

    wid = worker_id()
    logger.info("Worker %s starting, polling every %.1fs", wid, POLL_INTERVAL_SECONDS)

    while not _shutdown_requested:
        with session_scope() as db:
            claimed = claim_next_job(db)
        if claimed is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        logger.info("Worker %s claimed job %s (%s)", wid, claimed.job_id, claimed.job_type)
        run_claimed_job(claimed)

    logger.info("Worker %s shutting down", wid)


if __name__ == "__main__":
    run_forever()
