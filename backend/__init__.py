"""Local Automator backend package.

Single source of truth for the application version. Bumped per the
versioning discipline in CLAUDE.md (CalVer: YYYY.MM.DD.N — the
trailing N is a per-day serial that resets to 0 each day). All
surfaces — FastAPI app metadata, /api/v1/system/version, the SPA
footer — read it from here.
"""

__version__ = "2026.05.23.4"
