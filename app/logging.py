import logging
import os
from typing import Literal

import structlog

LoggerEnv = Literal["dev", "prod", "test"]


def configure_logging(env: LoggerEnv = "prod") -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        timestamper,
        structlog.processors.add_log_level,
    ]

    if env == "dev":
        processors = [
            *shared_processors,
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        processors = [
            *shared_processors,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


logger = structlog.get_logger()
