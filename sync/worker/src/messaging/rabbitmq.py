import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import pika

from logcontext import job_context, peek_job_id
from metrics import RABBITMQ_RECONNECTS

logger = logging.getLogger(__name__)


@dataclass
class QueueConfig:
    name: str
    durable: bool = True
    failed_suffix: str = "_failed"
    completed_suffix: str = "_completed"

    @property
    def failed_name(self) -> str:
        return f"{self.name}{self.failed_suffix}"

    @property
    def completed_name(self) -> str:
        return f"{self.name}{self.completed_suffix}"


CANCEL_EXCHANGE = "job_cancellations"


class QueueNames:
    """Named queues the worker consumes from / publishes to."""

    CONTENT_SYNC = "content_sync_jobs"
    INGESTION = "ingestion_jobs"
    METADATA_SYNC = "metadata_sync_jobs"
    JOB_PROGRESS_UPDATES = "job_progress_updates"


def _reconnect_backoff_seconds(
    attempt: int, *, base: float = 2.0, cap: float = 60.0
) -> float:
    """Exponential backoff (seconds) for the consume-loop reconnect retry.

    attempt is 1-indexed so the first wait is `base` seconds. Capped to
    avoid sleeping for hours after a long outage.
    """
    if attempt < 1:
        return 0.0
    return min(base * (2 ** (attempt - 1)), cap)


class RabbitMQClient:
    def __init__(self, url: str, max_retries: int = 5, retry_delay: int = 5):
        self.url = url
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.connection = None
        self.channel = None
        self._consumers = {}
        self._cancel_queue = None
        self._cancelled_jobs: set[str] = set()

    def _get_connection_parameters(self):
        # heartbeat is long because the consumer thread also services the
        # connection, Haystack polling does time.sleep() without pumping
        # pika, so a single long file would otherwise drop the heartbeat
        params = pika.URLParameters(self.url)
        params.heartbeat = 1800
        params.blocked_connection_timeout = 300
        params.socket_timeout = 300
        return params

    def _connect(self):
        for attempt in range(self.max_retries):
            try:
                if self.connection and not self.connection.is_closed:
                    try:
                        self.connection.close()
                    except Exception:
                        pass

                params = self._get_connection_parameters()
                self.connection = pika.BlockingConnection(params)
                self.channel = self.connection.channel()

                self._setup_cancel_queue()

                logger.info("Successfully connected to RabbitMQ")
                return True

            except Exception as e:
                logger.error(
                    f"Failed to connect to RabbitMQ (attempt {attempt + 1}): {e}"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    raise Exception(
                        f"Failed to connect to RabbitMQ after {self.max_retries} attempts"
                    )

        return False

    def _ensure_connection(self):
        if not self.connection or self.connection.is_closed:
            logger.info("Connection lost, reconnecting...")
            self._connect()

    def _setup_cancel_queue(self):
        try:
            self.channel.exchange_declare(
                exchange=CANCEL_EXCHANGE, exchange_type="fanout", durable=True
            )
            result = self.channel.queue_declare(queue="", exclusive=True)
            self._cancel_queue = result.method.queue
            self.channel.queue_bind(exchange=CANCEL_EXCHANGE, queue=self._cancel_queue)
            logger.debug(f"Cancel queue bound: {self._cancel_queue}")
        except Exception as e:
            logger.warning(f"Failed to set up cancel queue: {e}")
            self._cancel_queue = None

    def is_job_cancelled(self, job_id: str) -> bool:
        """True once a cancellation broadcast for job_id has been seen.

        Drains the exclusive cancel queue into ``_cancelled_jobs`` rather
        than discarding non-matching messages: a cancel for a job still
        sitting in the work queue can arrive while this worker processes
        another job, and must still be honored when that job is picked up
        later. The set is tiny (one id per cancellation) and resets on
        worker restart, along with the exclusive queue itself.
        """
        if not job_id:
            return False
        self._drain_cancellations()
        return str(job_id) in self._cancelled_jobs

    def _drain_cancellations(self) -> None:
        """Move all pending cancel broadcasts into ``_cancelled_jobs``."""
        if not self._cancel_queue:
            return
        try:
            while True:
                method, _, body = self.channel.basic_get(
                    queue=self._cancel_queue, auto_ack=True
                )
                if method is None:
                    break
                try:
                    msg = json.loads(body)
                    cancelled_id = msg.get("job_id")
                except (json.JSONDecodeError, AttributeError):
                    continue
                if cancelled_id:
                    self._cancelled_jobs.add(str(cancelled_id))
                    logger.info(f"Cancellation received for job {cancelled_id}")
        except Exception as e:
            # keep whatever was drained so far; membership check still runs
            logger.warning(f"Error checking cancellation: {e}")

    def setup_queue(self, queue: QueueConfig) -> None:
        """Declare the main queue and its failed/completed siblings."""
        self._ensure_connection()

        try:
            for suffix in ["", queue.failed_suffix, queue.completed_suffix]:
                queue_name = f"{queue.name}{suffix}"
                self.channel.queue_declare(queue=queue_name, durable=queue.durable)
                logger.debug(f"Declared queue: {queue_name}")
        except Exception as e:
            logger.error(f"Error setting up queue {queue.name}: {e}")
            raise

    def publish(
        self,
        queue: str,
        message: dict,
        properties: pika.BasicProperties | None = None,
        headers: dict | None = None,
        max_retries: int = 3,
    ) -> None:
        """Publish a message to a queue. Retries on failure."""
        if properties is None:
            properties = pika.BasicProperties(
                delivery_mode=2,
                headers=headers or {},
            )

        for attempt in range(max_retries):
            try:
                self._ensure_connection()

                self.channel.basic_publish(
                    exchange="",
                    routing_key=queue,
                    body=json.dumps(message),
                    properties=properties,
                )
                logger.debug(f"Published message to queue {queue}")
                return

            except Exception as e:
                logger.error(
                    f"Error publishing to queue {queue} (attempt {attempt + 1}): {e}"
                )
                if attempt < max_retries - 1:
                    time.sleep(1)
                    try:
                        self._connect()
                    except Exception:
                        pass
                else:
                    raise Exception(
                        f"Failed to publish message after {max_retries} attempts: {e}"
                    )

    def consume(self, queue: str, callback: Callable) -> None:
        """Register a callback for a queue; start_consuming polls it."""
        self._consumers[queue] = callback
        logger.info(f"Registered consumer callback for queue: {queue}")

    def start_consuming(
        self,
        max_reconnect_attempts: int = 10,
        backoff_base: float = 2.0,
        backoff_cap: float = 60.0,
        poll_interval: float = 1.0,
    ) -> None:
        """Pull-based consume loop with at-most-once delivery: ack at claim.

        Any non-KeyboardInterrupt exception (broker restart, network blip,
        channel closed) sleeps with exponential backoff then rebuilds the
        connection. A successful poll cycle resets the attempt counter.
        connection.sleep() during idle keeps heartbeats flowing.
        """
        reconnect_attempts = 0

        while True:
            try:
                self._ensure_connection()

                got_message = False
                for queue, callback in self._consumers.items():
                    method, properties, body = self.channel.basic_get(queue=queue)
                    if method is None:
                        continue
                    got_message = True
                    self.channel.basic_ack(delivery_tag=method.delivery_tag)
                    with job_context(peek_job_id(body), queue):
                        callback(self.channel, method, properties, body)

                reconnect_attempts = 0

                if not got_message:
                    self.connection.sleep(poll_interval)

            except KeyboardInterrupt:
                logger.info("Stopping consumer...")
                break

            except Exception as e:
                reconnect_attempts += 1
                RABBITMQ_RECONNECTS.inc()
                logger.error(
                    f"Unexpected error (attempt {reconnect_attempts}/{max_reconnect_attempts}): {e}"
                )
                if reconnect_attempts >= max_reconnect_attempts:
                    logger.critical("Max reconnect attempts reached. Exiting.")
                    raise
                delay = _reconnect_backoff_seconds(
                    reconnect_attempts, base=backoff_base, cap=backoff_cap
                )
                logger.info(
                    f"Reconnecting in {delay:.1f}s "
                    f"(attempt {reconnect_attempts + 1}/{max_reconnect_attempts})"
                )
                time.sleep(delay)
                # drop the old connection so _ensure_connection rebuilds it
                # instead of trusting the stale handle that just raised
                try:
                    if self.connection and not self.connection.is_closed:
                        self.connection.close()
                except Exception:
                    pass
                self.connection = None
                self.channel = None

    def close(self):
        try:
            if self.channel and not self.channel.is_closed:
                self.channel.close()
        except Exception:
            pass

        try:
            if self.connection and not self.connection.is_closed:
                self.connection.close()
        except Exception:
            pass

        logger.info("RabbitMQ connection closed")

    def __enter__(self):
        self._connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
