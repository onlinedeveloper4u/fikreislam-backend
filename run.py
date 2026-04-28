#!/usr/bin/env python3
"""
Entry point for running the FastAPI server.

Usage:
    python run.py
    # or
    uvicorn app.main:app --reload
"""

import uvicorn
from app.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
