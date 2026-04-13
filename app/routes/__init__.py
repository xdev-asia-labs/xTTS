"""Routes package — collects all routers."""
from app.routes.system import router as system_router
from app.routes.tts import router as tts_router

__all__ = ["system_router", "tts_router"]
