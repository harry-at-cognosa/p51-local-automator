from fastapi import APIRouter

from backend.config import API_URL_PREFIX
from backend.db.schemas import UserRead, UserCreate
from backend.auth.users import fastapi_users, auth_backend

from backend.api.users import router_users
from backend.api.workflows import router_workflows
from backend.api.dashboard import router_dashboard
from backend.api.settings import router_settings
from backend.api.scheduler import router_scheduler
from backend.api.manage_users import router_manage_users
from backend.api.manage_groups import router_manage_groups
from backend.api.group_settings import router_group_settings
from backend.api.artifacts import router_artifacts
from backend.api.files import router_files
from backend.api.gmail_oauth import router_gmail_oauth
from backend.api.google_calendar import router_google_calendar

api_router = APIRouter(prefix=API_URL_PREFIX)

# Auth routes from fastapi-users
api_router.include_router(
    fastapi_users.get_auth_router(auth_backend), prefix="/auth/jwt", tags=["Auth"]
)
api_router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth", tags=["Auth"]
)

# Application routes
api_router.include_router(router_users, tags=["Users"])
api_router.include_router(router_workflows, tags=["Workflows"])
api_router.include_router(router_dashboard, tags=["Dashboard"])
api_router.include_router(router_settings, tags=["Settings"])
api_router.include_router(router_scheduler)
api_router.include_router(router_manage_users, tags=["Manage Users"])
api_router.include_router(router_manage_groups, tags=["Manage Groups"])
api_router.include_router(router_group_settings, tags=["Group Settings"])
api_router.include_router(router_artifacts, tags=["Artifacts"])
api_router.include_router(router_files, tags=["Files"])
api_router.include_router(router_gmail_oauth, tags=["Gmail"])
api_router.include_router(router_google_calendar, tags=["Google Calendar"])
