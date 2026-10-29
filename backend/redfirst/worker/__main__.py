"""Worker process: ``python -m redfirst.worker [--once]``. Runs separately from the API."""

import argparse
import logging
import time

from redfirst.core.config import get_settings
from redfirst.db.session import make_engine
from redfirst.llm.factory import make_provider
from redfirst.llm.prompts import load_prompt
from redfirst.sandbox.executor import DockerExecutor
from redfirst.storage.blobs import BlobStore
from redfirst.worker.orchestrator import Deps, Orchestrator
from redfirst.worker.queue import claim_next, recover_lost

PROMPT = ("generate_test", "v1")


def main() -> None:
    parser = argparse.ArgumentParser(description="REDFIRST investigation worker")
    parser.add_argument("--once", action="store_true", help="process at most one job and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("redfirst.worker")

    settings = get_settings()
    engine = make_engine()
    deps = Deps(
        settings=settings, engine=engine, blobs=BlobStore(settings.data_dir / "blobs"),
        provider=make_provider(settings),
        executor=DockerExecutor(settings.sandbox_image, settings.sandbox_timeout_seconds,
                                settings.sandbox_memory),
        prompt=load_prompt(*PROMPT), work_root=settings.data_dir / "work",
    )
    for inv_id in recover_lost(engine):
        log.warning("marked %s as failed (worker lost)", inv_id)

    while True:
        inv_id = claim_next(engine)
        if inv_id:
            log.info("running investigation %s", inv_id)
            Orchestrator(deps, inv_id).run()
        if args.once:
            return
        if not inv_id:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
