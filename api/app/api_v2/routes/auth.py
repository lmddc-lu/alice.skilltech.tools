from faststream.rabbit.fastapi import RabbitRouter

from app.api_v2.deps import UserDep
from app.core.config import settings

router = RabbitRouter(settings.RABBITMQ_URL, tags=["auth"])


@router.get("/auth/user_info")
async def get_user_info(user_info: UserDep) -> UserDep:
    return user_info
