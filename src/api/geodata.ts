import type { MultiPolygon, Polygon } from "geojson";
import { api } from "./client";

/** One land parcel from the public Moldova cadastral service. Rings are WGS84 longitude, latitude. */
export interface CadastralParcel {
  cadastralCode: string | null;
  parcelCode: string | null;
  area: string | null;
  landUse: string | null;
  propertyType: string | null;
  locality: string | null;
  district: string | null;
  geometry: Polygon | MultiPolygon;
}

export interface ParcelLookup {
  lat: number;
  lon: number;
  parcel: CadastralParcel | null;
}

export async function lookupParcel(lat: number, lon: number): Promise<ParcelLookup> {
  const res = await api.get<ParcelLookup>("/geodata/parcel", { params: { lat, lon } });
  return res.data;
}
