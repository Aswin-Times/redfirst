"""Worker process: ``python -m redfirst.worker [--once]``. Runs separately from the API.

Several workers may run at once. Each claims investigations under its own id, keeps a lease on
the one it is running (heartbeat thread), and on every loop iteration fails runs whose owner's
lease has expired, so a crashed worker's run is eventually closed by any surviving worker.
"""

import argparse
import logging
import os
import sys
import time

from sqlalchemy import Engine

from redfirst.core.config import Settings, get_settings
from redfirst.db.session import make_engine
from redfirst.llm.factory import make_provider
from redfirst.llm.prompts import load_prompt
from redfirst.sandbox.executor import DockerExecutor
from redfirst.sandbox.runner import docker_available, sandbox_image_available
from redfirst.storage.blobs import BlobStore
from redfirst.worker.lease import LeaseKeeper
from redfirst.worker.orchestrator import Deps, Orchestrator
from redfirst.worker.queue import claim_next, default_worker_id, recover_lost

PROMPT = ("generate_test", "v4")  # v4 adds the direct-check rule for wrong-value bugs (M9.2)

log = logging.getLogger("redfirst.worker")


def preflight(settings: Settings) -> tuple[list[str], list[str]]:
    """What stops this worker from running investigations (problems) or may (warnings).

    Without Docker every claimed investigation would fail, so a worker that cannot run them must
    not claim them: they stay queued for a worker that can.
    """
    problems: list[str] = []
    warnings: list[str] = []
    if not docker_available():
        problems.append(
            "Docker is not available (the docker command is missing or its engine is not "
            "running). Start Docker Desktop, or install it (README: Running a real "
            "investigation). Investigations stay queued until a worker with Docker picks them up.")
    elif not sandbox_image_available(settings.sandbox_image):
        problems.append(
            f"Sandbox image {settings.sandbox_image} not found. Build it from the repository "
            f"root: docker build -t {settings.sandbox_image} sandbox-images/python")
    has_key = bool(settings.llm_api_key and settings.llm_api_key.get_secret_value().strip())
    if not has_key and not os.environ.get("ANTHROPIC_API_KEY"):
        warnings.append(
            "No Anthropic API key configured (REDFIRST_LLM_API_KEY in backend/.env, or "
            "ANTHROPIC_API_KEY). Test generation will fail unless the SDK finds credentials "
            "elsewhere, such as an `ant auth login` profile.")
    return problems, warnings


def run_one(deps: Deps, engine: Engine, worker_id: str, lease_seconds: float) -> str | None:
    """One loop iteration: recover expired runs, then claim and run at most one investigation."""
    for inv_id in recover_lost(engine):
        log.warning("marked %s as failed: its worker's lease expired", inv_id)
    inv_id = claim_next(engine, worker_id=worker_id, lease_seconds=lease_seconds)
    if inv_id:
        log.info("worker %s running investigation %s", worker_id, inv_id)
        with LeaseKeeper(engine, inv_id, worker_id, lease_seconds) as lease:
            Orchestrator(deps, inv_id, lease=lease).run()
    return inv_id


def main() -> None:
    parser = argparse.ArgumentParser(description="REDFIRST investigation worker")
    parser.add_argument("--once", action="store_true", help="process at most one job and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    settings = get_settings()
    problems, warnings = preflight(settings)
    for message in warnings:
        log.warning(message)
    if problems:
        for message in problems:
            log.error(message)
        log.error("worker not started: nothing was claimed")
        sys.exit(2)
    engine = make_engine()
    deps = Deps(
        settings=settings, engine=engine, blobs=BlobStore(settings.data_dir / "blobs"),
        provider=make_provider(settings),
        executor=DockerExecutor(settings.sandbox_image, settings.sandbox_timeout_seconds,
                                settings.sandbox_memory),
        prompt=load_prompt(*PROMPT), work_root=settings.data_dir / "work",
    )
    worker_id = default_worker_id()
    log.info("worker %s started", worker_id)
    while True:
        inv_id = run_one(deps, engine, worker_id, settings.worker_lease_seconds)
        if args.once:
            return
        if not inv_id:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
