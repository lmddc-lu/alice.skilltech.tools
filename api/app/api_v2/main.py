from fastapi import APIRouter

import app.api_v2.routes.chatbots.avatar  # noqa: F401
import app.api_v2.routes.chatbots.branding  # noqa: F401
import app.api_v2.routes.chatbots.chat  # noqa: F401
import app.api_v2.routes.chatbots.creation  # noqa: F401
import app.api_v2.routes.chatbots.files  # noqa: F401
import app.api_v2.routes.chatbots.jobs  # noqa: F401
import app.api_v2.routes.chatbots.lifecycle  # noqa: F401
import app.api_v2.routes.chatbots.listing  # noqa: F401
import app.api_v2.routes.chatbots.moodle  # noqa: F401
from app.api_v2.routes import monitoring, moodle, oauth, utils, workers
from app.api_v2.routes.chatbots.router import router as chatbots_router

api_v2_router = APIRouter()
api_v2_router.include_router(chatbots_router)
api_v2_router.include_router(moodle.router)
api_v2_router.include_router(workers.router)
api_v2_router.include_router(utils.router)
api_v2_router.include_router(oauth.router)
api_v2_router.include_router(monitoring.router)
