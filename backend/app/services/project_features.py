"""A project's annotations as rendered GeoJSON, held in memory after the first read.

Opening a mosaicked vineyard reads tens of thousands of annotation rows and tens of megabytes of
geometry, which on a hosted database is seconds of waiting. None of it changes until an annotation
is added or an upload replaces them, so the rendered bytes are kept and served again.

The bytes are cached rather than the feature dicts they came from: as Python objects the same
collection costs several times the memory, and every response would have to serialize it again.

An entry is only served while the project's stamp still matches, so annotations written outside the
request that cached them, by another process or by `python -m app.backfill_annotations`, are read
fresh instead of going stale.
"""

import json
import threading
from collections import OrderedDict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.models import Annotation
from app.services.annotations import feature_collection, features_by_project

MAX_BYTES = int(config.PROJECT_CACHE_MB * 1024 * 1024)

# How many annotations the project has, the newest one, and the raster they were measured on. Ids
# come from a sequence and raster ids are random, so any write the project sees changes the stamp.
Stamp = tuple[int, int, str]

_lock = threading.Lock()
_cached: OrderedDict[int, tuple[Stamp, bytes]] = OrderedDict()  # least recently read first
_cached_bytes = 0


def _stamp(db: Session, project_id: int) -> Stamp:
    count, newest, raster_id = db.execute(
        select(
            func.count(Annotation.id),
            func.coalesce(func.max(Annotation.id), 0),
            func.coalesce(func.max(Annotation.raster_id), ""),
        ).where(Annotation.project_id == project_id)
    ).one()
    return count, newest, raster_id


def _read(project_id: int, stamp: Stamp) -> bytes | None:
    with _lock:
        entry = _cached.get(project_id)
        if entry is None or entry[0] != stamp:
            return None
        _cached.move_to_end(project_id)
        return entry[1]


def _discard(project_id: int) -> None:
    """Caller holds the lock."""
    global _cached_bytes
    entry = _cached.pop(project_id, None)
    if entry is not None:
        _cached_bytes -= len(entry[1])


def _write(project_id: int, stamp: Stamp, body: bytes) -> None:
    global _cached_bytes
    if len(body) > MAX_BYTES:
        return
    with _lock:
        _discard(project_id)
        _cached[project_id] = (stamp, body)
        _cached_bytes += len(body)
        while _cached_bytes > MAX_BYTES:
            _discard(next(iter(_cached)))


def forget(project_id: int) -> None:
    with _lock:
        _discard(project_id)


def features_json(db: Session, project_id: int) -> bytes:
    """The project's annotations as a GeoJSON FeatureCollection, serialized."""
    # Stamped before the read, so a write landing in between costs one more read and is never served stale.
    stamp = _stamp(db, project_id)
    cached = _read(project_id, stamp)
    if cached is not None:
        return cached
    features = features_by_project(db, [project_id])[project_id]
    body = json.dumps(feature_collection(features)).encode()
    _write(project_id, stamp, body)
    return body
