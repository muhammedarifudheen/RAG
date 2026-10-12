import logging

from worker.config import settings

logger = logging.getLogger("worker")


def main() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logger.info("Nothing to run here yet. To ingest a repository: python -m worker.ingest <url>")


if __name__ == "__main__":
    main()
