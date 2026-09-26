import type { FeatureCollection } from "geojson";

/** XYZ Web Mercator PNG tiles served by the backend for an uploaded raster. */
export type RasterTiles = {
  url: string; // template with {z}/{x}/{y}
  minzoom: number;
  maxzoom: number;
};

export type ProcessResult = {
  tiles: RasterTiles | null;
  boundsEpsg32635: [number, number, number, number]; // [minX, minY, maxX, maxY]
  features: FeatureCollection;
};

export type FeatureLabel = "vineyard" | "waste" | "row" | "interrow_area" | "route";

/** Properties carried by features in `ProcessResult.features` (coordinates are EPSG:32635 metres). */
export type ProcessFeatureProperties = {
  label: FeatureLabel;
  vineyard_id?: string | number | null;
  row_id?: string | number | null;
  row_structure?: string | null;
  interrow_cover?: string | null;
  length_m?: number | null;
  grapevine_count?: number | null;
  area_m2?: number | null;
  area_ha?: number | null;
};
