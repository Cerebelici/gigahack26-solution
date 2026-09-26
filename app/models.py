from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, DOUBLE_PRECISION, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

MAP_SRID = 32635
LABELS = ("vineyard", "waste", "row", "interrow_area")
SHAPES = ("polygon", "polyline", "box")


class Base(DeclarativeBase):
    pass


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)  # stored lower-cased
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(Text)  # argon2id, never the plaintext
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Raster(Base):
    """An uploaded GeoTIFF. Tiles come from its COG; its pixel grid places pixel annotations on the map.

    The project's current raster is its most recently uploaded one. Older rasters stay because
    annotations measured on them still reference their geotransform.
    """

    __tablename__ = "rasters"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # folder name under UPLOAD_DIR
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    # Affine (a, b, c, d, e, f) from pixel corner (x, y) to CRS units: E = a*x + b*y + c, N = d*x + e*y + f.
    transform: Mapped[list[float]] = mapped_column(ARRAY(DOUBLE_PRECISION, dimensions=1))
    crs_wkt: Mapped[str] = mapped_column(Text)
    srid: Mapped[int | None] = mapped_column(Integer)  # EPSG code of crs_wkt, when it has one
    bounds_epsg32635: Mapped[list[float]] = mapped_column(ARRAY(DOUBLE_PRECISION, dimensions=1))
    minzoom: Mapped[int] = mapped_column(Integer)
    maxzoom: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Annotation(Base):
    """One CV object, stored both as the model's pixel coordinates and as a map geometry."""

    __tablename__ = "annotations"
    __table_args__ = (
        CheckConstraint(_in("label", LABELS), name="annotations_label_check"),
        CheckConstraint(_in("shape", SHAPES), name="annotations_shape_check"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    raster_id: Mapped[str] = mapped_column(ForeignKey("rasters.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(32))
    shape: Mapped[str] = mapped_column(String(16))
    # Pixel rings exactly as received: [[[x, y], ...], ...], origin top-left, y down. For a box this
    # is its four corners, and the box as sent is kept in pixel_box.
    pixel_rings: Mapped[list[Any]] = mapped_column(JSONB)
    pixel_box: Mapped[dict[str, float] | None] = mapped_column(JSONB)
    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=MAP_SRID, spatial_index=True), nullable=False, deferred=True
    )
    vineyard_id: Mapped[str | None] = mapped_column(Text)
    row_id: Mapped[str | None] = mapped_column(Text)
    row_structure: Mapped[str | None] = mapped_column(Text)
    interrow_cover: Mapped[str | None] = mapped_column(Text)
    length_m: Mapped[float | None] = mapped_column(Float)
    grapevine_count: Mapped[int | None] = mapped_column(Integer)
    area_m2: Mapped[float | None] = mapped_column(Float)
    area_ha: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
