"""Find challenge GeoTIFFs in extracted part folders or in the five zip collections."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_TILE_NAME = re.compile(r"siret3_r\d+_c\d+\.tif$", re.IGNORECASE)


@dataclass(frozen=True)
class TileSource:
    name: str
    path: Path
    member: Optional[str] = None

    def rasterio_path(self) -> str:
        if self.member:
            return f"/vsizip/{self.path}/{self.member}"
        return str(self.path)


def discover_tiles(root: Path) -> list[TileSource]:
    """Return one source per tile name. An extracted tif wins over a zip member."""
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(root)

    extracted: dict[str, TileSource] = {}
    zipped: dict[str, TileSource] = {}

    if root.is_file() and root.suffix.lower() == ".zip":
        _collect_zip(root, zipped)
    else:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in {".tif", ".tiff"} and _TILE_NAME.search(path.name):
                extracted[path.name] = TileSource(name=path.name, path=path)
            elif path.suffix.lower() == ".zip":
                _collect_zip(path, zipped)

    names = set(extracted) | set(zipped)
    chosen = [extracted.get(name) or zipped[name] for name in sorted(names)]
    return chosen


def _collect_zip(path: Path, into: dict[str, TileSource]) -> None:
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return
    with archive:
        for info in archive.infolist():
            member_name = Path(info.filename).name
            if _TILE_NAME.search(member_name) and member_name not in into:
                into[member_name] = TileSource(name=member_name, path=path, member=info.filename)
