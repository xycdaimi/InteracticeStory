from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.v1.stories import router as stories_router

api_router = APIRouter()
api_router.include_router(stories_router)
