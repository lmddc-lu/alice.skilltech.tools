"""Shared FastStream RabbitRouter for the chatbots package.

All sub-modules attach HTTP routes to this single instance and publish
AMQP messages through ``router.broker``. One router per package keeps a
single broker connection for the chatbots domain.
"""

from faststream.rabbit.fastapi import RabbitRouter

from app.core.config import settings

router = RabbitRouter(settings.RABBITMQ_URL, tags=["chatbots_v2"])
