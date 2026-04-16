from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.db.models import User
from backend.auth.users import current_active_user
from backend.services.scheduler_service import scheduler

router_scheduler = APIRouter(prefix="/scheduler", tags=["Scheduler"])


class SchedulerStatus(BaseModel):
    running: bool


@router_scheduler.get("/status", response_model=SchedulerStatus)
async def get_status(user: User = Depends(current_active_user)):
    return SchedulerStatus(running=scheduler.is_running)


@router_scheduler.post("/start", response_model=SchedulerStatus)
async def start_scheduler(user: User = Depends(current_active_user)):
    if not user.is_superuser:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Superuser required")
    scheduler.start()
    return SchedulerStatus(running=scheduler.is_running)


@router_scheduler.post("/stop", response_model=SchedulerStatus)
async def stop_scheduler(user: User = Depends(current_active_user)):
    if not user.is_superuser:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Superuser required")
    scheduler.stop()
    return SchedulerStatus(running=scheduler.is_running)
