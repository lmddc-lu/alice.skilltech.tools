import json
import logging
from uuid import UUID

import aio_pika

logger = logging.getLogger(__name__)

CANCEL_EXCHANGE = "job_cancellations"


async def broadcast_job_cancellations(rabbitmq_url: str, job_ids: list[UUID]) -> None:
    """Publish cancellation signals for the given job IDs on the fanout."""
    if not job_ids:
        return

    connection = await aio_pika.connect_robust(rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            CANCEL_EXCHANGE,
            aio_pika.ExchangeType.FANOUT,
            durable=True,
        )
        for job_id in job_ids:
            await exchange.publish(
                aio_pika.Message(body=json.dumps({"job_id": str(job_id)}).encode()),
                routing_key="",
            )
    logger.info(f"Broadcast cancellation for {len(job_ids)} jobs")
