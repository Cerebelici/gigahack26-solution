import logging
import logging.config
import re

from uvicorn.config import LOGGING_CONFIG

from app.log import configure_logging

TIMESTAMP = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}"


def test_uvicorn_logs_include_timestamp():
    logging.config.dictConfig(LOGGING_CONFIG)
    configure_logging()

    error_handler = logging.getLogger("uvicorn").handlers[0]
    record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 0, "Application startup complete.", None, None)
    assert re.fullmatch(rf"{TIMESTAMP} INFO:     Application startup complete\.", error_handler.format(record))

    access_handler = logging.getLogger("uvicorn.access").handlers[0]
    args = ("127.0.0.1:5000", "POST", "/process-tif", "1.1", 200)
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, '%s - "%s %s HTTP/%s" %d', args, None)
    assert re.fullmatch(
        rf'{TIMESTAMP} INFO:     127\.0\.0\.1:5000 - "POST /process-tif HTTP/1\.1" 200 OK',
        access_handler.format(record),
    )
