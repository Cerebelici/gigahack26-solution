import type { FeatureCollection } from "geojson";
import type { RasterTiles } from "../../types/process";

export type { ProcessResult, RasterTiles } from "../../types/process";

export type LngLatPair = [number, number];

export interface FieldFeature {
  fid: number;
  label: string;
  block: string;
  rowId: string | null;
  props: Record<string, unknown>;
  lengthM: number | null;
  areaM2: number | null;
}

export interface FieldData {
  tiles: RasterTiles | null;
  imageCorners: [LngLatPair, LngLatPair, LngLatPair, LngLatPair];
  bounds: [LngLatPair, LngLatPair];
  items: FieldFeature[];
  mapFeatures: FeatureCollection;
  blocks: string[];
}
