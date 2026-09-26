import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app import config  # noqa: F401  loads .env before anything reads the environment
from app.log import configure_logging
from app.routers import auth, process_tif, projects, tiles

configure_logging()
logger = logging.getLogger(__name__)

DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173,http://127.0.0.1:5173,"
    "http://localhost:4173,http://127.0.0.1:4173"
)

app = FastAPI(title="Geobelic Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(OperationalError)
async def database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
    logger.error("Database unavailable: %s", exc.orig)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable."})


app.include_router(process_tif.router)
app.include_router(tiles.router)
app.include_router(auth.router)
app.include_router(projects.router)
