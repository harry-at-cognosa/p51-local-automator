from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import CORS_ORIGINS
from backend.auth.middleware import refresh_last_seen
from backend.services.logger_service import setup_logging
from backend.db.seed import run_seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await run_seed()
    yield


app = FastAPI(
    title="Local Automator API",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(refresh_last_seen)],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
