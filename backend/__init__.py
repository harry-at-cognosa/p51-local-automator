"""Local Automator backend package.

Single source of truth for the application version. Bumped per the
versioning discipline in CLAUDE.md (CalVer: YYYY.MM.PATCH). All
surfaces — FastAPI app metadata, /api/v1/system/version, the SPA
footer — read it from here.
"""

__version__ = "2026.05.0"
