import proj4 from "proj4";
import type { Feature, Geometry, Position } from "geojson";
import type { FieldData, FieldFeature, LngLatPair, ProcessResult } from "./types";

export const EPSG32635 = "+proj=utm +zone=35 +datum=WGS84 +units=m +no_defs";

const utmToWgs84 = proj4(EPSG32635, "EPSG:4326");

export function toLngLat([x, y]: Position): LngLatPair {
  const [lng, lat] = utmToWgs84.forward([x, y]);
  return [lng, lat];
}

/** Inverse of `toLngLat`. Map clicks come back as EPSG:32635 metres. */
export function fromLngLat([lng, lat]: LngLatPair): [number, number] {
  const [x, y] = utmToWgs84.inverse([lng, lat]);
  return [x, y];
}

export function roundMetres(value: number): number {
  return Math.round(value * 100) / 100;
}

export function mapGeometry(geometry: Geometry, fn: (position: Position) => Position): Geometry {
  switch (geometry.type) {
    case "Point":
      return { type: "Point", coordinates: fn(geometry.coordinates) };
    case "MultiPoint":
    case "LineString":
      return { type: geometry.type, coordinates: geometry.coordinates.map(fn) };
    case "MultiLineString":
    case "Polygon":
      return {
        type: geometry.type,
        coordinates: geometry.coordinates.map((ring) => ring.map(fn)),
      };
    case "MultiPolygon":
      return {
        type: "MultiPolygon",
        coordinates: geometry.coordinates.map((poly) => poly.map((ring) => ring.map(fn))),
      };
    case "GeometryCollection":
      return { type: "GeometryCollection", geometries: geometry.geometries.map((g) => mapGeometry(g, fn)) };
  }
}

function projectGeometry(geometry: Geometry): Geometry {
  return mapGeometry(geometry, toLngLat);
}

function pathLength(coords: Position[]): number {
  let total = 0;
  for (let i = 1; i < coords.length; i++) {
    total += Math.hypot(coords[i][0] - coords[i - 1][0], coords[i][1] - coords[i - 1][1]);
  }
  return total;
}

function ringArea(ring: Position[]): number {
  let sum = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    sum += (ring[j][0] + ring[i][0]) * (ring[j][1] - ring[i][1]);
  }
  return Math.abs(sum) / 2;
}

function polygonArea(rings: Position[][]): number {
  const [outer, ...holes] = rings;
  if (!outer) return 0;
  return holes.reduce((area, hole) => area - ringArea(hole), ringArea(outer));
}

/** Geometry must be in metres (EPSG:32635), not degrees. */
export function measureLength(geometry: Geometry): number | null {
  if (geometry.type === "LineString") return pathLength(geometry.coordinates);
  if (geometry.type === "MultiLineString") {
    return geometry.coordinates.reduce((sum, line) => sum + pathLength(line), 0);
  }
  return null;
}

/** Geometry must be in metres (EPSG:32635), not degrees. */
export function measureArea(geometry: Geometry): number | null {
  if (geometry.type === "Polygon") return polygonArea(geometry.coordinates);
  if (geometry.type === "MultiPolygon") {
    return geometry.coordinates.reduce((sum, poly) => sum + polygonArea(poly), 0);
  }
  return null;
}

export function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) {
    return Number(value);
  }
  return null;
}

function asId(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value).trim();
}

export function buildFieldData(result: ProcessResult): FieldData {
  const [minX, minY, maxX, maxY] = result.boundsEpsg32635;
  const items: FieldFeature[] = [];
  const mapFeatures: Feature[] = [];

  result.features.features.forEach((feature) => {
    if (!feature.geometry) return;
    const props = feature.properties ?? {};
    const fid = items.length;
    const label = asId(props.label) || "unknown";
    const block = asId(props.vineyard_id);
    const rowId = asId(props.row_id) || null;

    items.push({
      fid,
      label,
      block,
      rowId,
      props,
      lengthM: asNumber(props.length_m) ?? measureLength(feature.geometry),
      areaM2: asNumber(props.area_m2) ?? measureArea(feature.geometry),
    });
    mapFeatures.push({
      type: "Feature",
      geometry: projectGeometry(feature.geometry),
      properties: { fid, label, block },
    });
  });

  const blocks = [...new Set(items.map((item) => item.block).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b, undefined, { numeric: true }),
  );

  const imageCorners: FieldData["imageCorners"] = [
    toLngLat([minX, maxY]),
    toLngLat([maxX, maxY]),
    toLngLat([maxX, minY]),
    toLngLat([minX, minY]),
  ];

  return {
    tiles: result.tiles,
    imageCorners,
    bounds: lngLatBox(imageCorners),
    items,
    mapFeatures: { type: "FeatureCollection", features: mapFeatures },
    blocks,
  };
}

export function collectPositions(geometry: Geometry, out: Position[]): void {
  switch (geometry.type) {
    case "Point":
      out.push(geometry.coordinates);
      break;
    case "MultiPoint":
    case "LineString":
      out.push(...geometry.coordinates);
      break;
    case "MultiLineString":
    case "Polygon":
      geometry.coordinates.forEach((ring) => out.push(...ring));
      break;
    case "MultiPolygon":
      geometry.coordinates.forEach((poly) => poly.forEach((ring) => out.push(...ring)));
      break;
    case "GeometryCollection":
      geometry.geometries.forEach((g) => collectPositions(g, out));
      break;
  }
}

function lngLatBox(positions: Position[]): [LngLatPair, LngLatPair] {
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (const [lng, lat] of positions) {
    west = Math.min(west, lng);
    south = Math.min(south, lat);
    east = Math.max(east, lng);
    north = Math.max(north, lat);
  }
  return [
    [west, south],
    [east, north],
  ];
}

/** Bounding box of the projected (WGS84) features that belong to `block`. */
export function blockBounds(data: FieldData, block: string): [LngLatPair, LngLatPair] | null {
  const positions: Position[] = [];
  data.mapFeatures.features.forEach((feature) => {
    if (feature.properties?.block === block && feature.geometry) {
      collectPositions(feature.geometry, positions);
    }
  });
  return positions.length ? lngLatBox(positions) : null;
}

export function formatMetres(value: number): string {
  return `${value.toFixed(1)} m`;
}

export function formatArea(value: number): string {
  return `${value.toFixed(2)} m²`;
}

export function formatHectares(value: number): string {
  return `${value.toFixed(4)} ha`;
}