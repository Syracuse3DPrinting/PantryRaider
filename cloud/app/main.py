"""Pantry Raider Cloud: the hosted subscription service.

A separate FastAPI app from the self-hosted Pantry Raider in service/; the
two share nothing at import time. Design: docs/design/cloud-platform.md.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import CLOUD_VERSION
from .database import init_db
from .routers import accounts, ai, instances, stripe_webhook


@asynccontextmanager
async def lifespan(app: FastAPI):
    # create_all for now; becomes `alembic upgrade head` in the entrypoint
    # once migrations exist (see the design doc's migration section).
    init_db()
    yield


app = FastAPI(title="Pantry Raider Cloud", version=CLOUD_VERSION,
              lifespan=lifespan)

app.include_router(accounts.router)
app.include_router(instances.router)
app.include_router(ai.router)
app.include_router(stripe_webhook.router)


@app.get("/health")
def health():
    return {"status": "ok", "app": "pantryraider-cloud", "version": CLOUD_VERSION}
