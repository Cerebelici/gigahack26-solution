from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.services.geodata import GeodataError, fetch_json, lookup_parcel

router = APIRouter(tags=["geodata"])


class ParcelGeometry(BaseModel):
    type: Literal["Polygon", "MultiPolygon"]
    coordinates: list


class ParcelOut(BaseModel):
    cadastralCode: str | None
    parcelCode: str | None
    area: str | None
    landUse: str | None
    propertyType: str | None
    locality: str | None
    district: str | None
    geometry: ParcelGeometry


class ParcelLookupOut(BaseModel):
    lat: float
    lon: float
    parcel: ParcelOut | None


def wfs_fetch() -> Callable[[str], dict]:
    return fetch_json


@router.get("/geodata/parcel", response_model=ParcelLookupOut)
def get_parcel(
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    fetch: Annotated[Callable[[str], dict], Depends(wfs_fetch)],
) -> ParcelLookupOut:
    """Land parcel under a WGS84 point, from the public Moldova cadastral service.

    Public, like the map tiles: the demo map looks parcels up before anyone signs in.
    """
    try:
        return lookup_parcel(lat, lon, fetch=fetch)
    except GeodataError as exc:
        raise HTTPException(status_code=502, detail="Cadastral service is unavailable.") from exc
