"""API v1 router aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from buddle.api.v1.admin import admin_router
from buddle.api.v1.argument_chat_ws import router as argument_chat_router
from buddle.api.v1.auth import router as auth_router
from buddle.api.v1.bookmarks import router as bookmarks_router
from buddle.api.v1.context_notes import router as context_notes_router
from buddle.api.v1.debate import router as debate_router
from buddle.api.v1.dialogue import router as dialogue_router
from buddle.api.v1.feed import router as feed_router
from buddle.api.v1.inbox import router as inbox_router
from buddle.api.v1.knowledge import router as knowledge_router
from buddle.api.v1.notifications import router as notifications_router
from buddle.api.v1.persona_models import router as persona_models_router
from buddle.api.v1.personas import router as personas_router
from buddle.api.v1.plaza import router as plaza_router
from buddle.api.v1.posts import router as posts_router
from buddle.api.v1.profile import router as profile_router
from buddle.api.v1.proximity import router as proximity_router
from buddle.api.v1.relationship import router as relationship_router
from buddle.api.v1.sessions import router as sessions_router
from buddle.api.v1.tags import router as tags_router
from buddle.api.v1.users import router as users_router

api_v1_router = APIRouter(prefix="/v1")

api_v1_router.include_router(auth_router)
api_v1_router.include_router(users_router)
api_v1_router.include_router(profile_router)
api_v1_router.include_router(personas_router)
api_v1_router.include_router(relationship_router)
api_v1_router.include_router(tags_router)
api_v1_router.include_router(debate_router)
api_v1_router.include_router(context_notes_router)
api_v1_router.include_router(persona_models_router)
api_v1_router.include_router(posts_router)
api_v1_router.include_router(feed_router)
api_v1_router.include_router(bookmarks_router)
api_v1_router.include_router(notifications_router)
api_v1_router.include_router(inbox_router)
api_v1_router.include_router(dialogue_router)
api_v1_router.include_router(argument_chat_router)
api_v1_router.include_router(plaza_router)
api_v1_router.include_router(proximity_router)
api_v1_router.include_router(sessions_router)
api_v1_router.include_router(knowledge_router)
api_v1_router.include_router(admin_router)


@api_v1_router.get("/", include_in_schema=False)
async def v1_root() -> dict[str, str]:
    return {"message": "buddle API v1"}
