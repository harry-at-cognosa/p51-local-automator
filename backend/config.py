import os

WORK_DIR = os.path.dirname(os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(WORK_DIR, '.env'), verbose=True)

API_URL_PREFIX = '/api/v1'
FRONTEND_DIR_STATIC = os.path.join(os.path.dirname(__file__), 'static')

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/p51_automator")
DATABASE_SYNC_URL = os.getenv("DATABASE_SYNC_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/p51_automator")
SECRET = os.getenv("SECRET", "change-me-in-production")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

CORS_ORIGINS = [s.strip() for s in os.getenv("CORS_ORIGINS", "").split(",") if s.strip()]

SCHEDULER_CHECK_INTERVAL_SECONDS = int(os.getenv("SCHEDULER_CHECK_INTERVAL_SECONDS", "60"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Track B Phase B1 — Gmail OAuth integration. Empty defaults mean the
# Gmail integration is not configured on this server; OAuth endpoints
# return 503 until all three are set. Each customer registers their own
# GCP project per docs/track_b_gmail_workspace_scoping_260426.md.
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")
