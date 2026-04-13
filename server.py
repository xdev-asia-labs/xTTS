#!/usr/bin/env python3
"""xTTS entry point — thin wrapper that creates the app and runs uvicorn."""
import uvicorn

from app import create_app
from app.config import settings

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
    )
