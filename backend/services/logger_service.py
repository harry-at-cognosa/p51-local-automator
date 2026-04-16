import structlog
from structlog._log_levels import _NAME_TO_LEVEL
from backend.config import LOG_LEVEL


def setup_logging():
    level = _NAME_TO_LEVEL.get(LOG_LEVEL.lower(), 20)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "p51_automator"):
    return structlog.get_logger(name)
