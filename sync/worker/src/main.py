import logging
import sys

from config import Config
from metrics import start_metrics_server
from worker import SyncWorker


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)

    try:
        config = Config.from_env()
        start_metrics_server(config.worker_metrics_port)
        worker = SyncWorker(config)
        worker.start()
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        # nonzero exit so docker restarts us
        sys.exit(1)


if __name__ == "__main__":
    main()
