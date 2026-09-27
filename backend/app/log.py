import logging

from uvicorn.logging import AccessFormatter, DefaultFormatter

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_FORMAT = "%(asctime)s.%(msecs)03d %(levelprefix)s %(message)s"
ACCESS_FORMAT = '%(asctime)s.%(msecs)03d %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'


def configure_logging() -> None:
    """Add timestamps to uvicorn's log lines.

    Must run after uvicorn has applied its own log config, which it does in the server
    process before importing the app, so calling this at app import time is enough.
    """
    for name in ("uvicorn", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            formatter = handler.formatter
            if isinstance(formatter, AccessFormatter):
                handler.setFormatter(AccessFormatter(ACCESS_FORMAT, DATE_FORMAT, use_colors=formatter.use_colors))
            elif isinstance(formatter, DefaultFormatter):
                handler.setFormatter(DefaultFormatter(DEFAULT_FORMAT, DATE_FORMAT, use_colors=formatter.use_colors))
