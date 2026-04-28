"""
Fikr-e-Islam — Internet Archive Backend Service

A FastAPI microservice that wraps the official `internetarchive` Python
library, exposing secure REST endpoints for:
  • Upload   (audio / video / book + optional cover image)
  • Metadata update
  • File rename (copy + delete)
  • File delete
  • Item delete (all files)
  • Derive trigger

The Next.js frontend calls these endpoints instead of doing raw S3 PUTs.
"""

import os
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes import ia_router

# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("fikreislam-ia")


# ── Lifespan (startup / shutdown) ────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("IA Backend starting — credentials %s",
                "OK" if settings.ia_access_key else "MISSING ⚠️")
    # Create temp upload dir
    os.makedirs("uploads", exist_ok=True)
    yield
    logger.info("IA Backend shutting down")


# ── App ──────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Fikr-e-Islam IA Backend",
    version="1.0.0",
    description="Secure Internet Archive proxy using the official Python library",
    lifespan=lifespan,
)

# CORS — allow the Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routes
app.include_router(ia_router, prefix="/api/ia", tags=["Internet Archive"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "fikreislam-ia-backend"}
