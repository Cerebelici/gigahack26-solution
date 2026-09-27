import type { Geometry, Position } from "geojson";
import type { FieldFeature } from "../map/types";
import type { Metres, RoutePlanRequest } from "../../types/project";
import type { RouteTypeId } from "./routeTypes";

/**
 * Row gaps are rows marked `disrupted` (a gap of at least 5 m, including missing planting).
 * Derived `inspection` features count too, once the pipeline emits them.
 */
export function isRowGap(item: FieldFeature): boolean {
  if (item.label === "inspection") return true;
  return item.label === "row" && item.props.row_structure === "disrupted";
}

export function isWaste(item: FieldFeature): boolean {
  return item.label === "waste";
}

/**
 * Objects Select targets may add or remove.
 *
 * A row gap is the same feature as its row axis: a `row` with `row_structure === "disrupted"`.
 * The map hits that line through `row-line` / `row-hit`, so the gap stays manually toggleable.
 * Inter-rows and every other row axis are not targets. A distinct `inspection` feature, if the
 * pipeline emits one, is a gap and stays toggleable.
 */
export function isSelectableRouteTarget(item: FieldFeature): boolean {
  if (item.label === "interrow_area") return false;
  if (item.label === "row" && !isRowGap(item)) return false;
  return true;
}

export function matchesRouteType(routeType: RouteTypeId, item: FieldFeature): boolean {
  switch (routeType) {
    case "waste":
      return isWaste(item);
    case "inspection":
      return isRowGap(item);
  }
}

export function routeTargetFids(routeType: RouteTypeId, items: readonly FieldFeature[]): number[] {
  return items.filter((item) => matchesRouteType(routeType, item)).map((item) => item.fid);
}

/** Features of one vineyard block. `null` keeps the whole field. */
export function featuresInBlock(items: readonly FieldFeature[], block: string | null): readonly FieldFeature[] {
  if (!block) return items;
  return items.filter((item) => item.block === block);
}

export type RouteClickMode = {
  pick: boolean;
  place: boolean;
};

export type MapHit = {
  fid: number;
  label: string;
  /** Map layer that produced the hit. Row axes use `row-line`; inter-rows use `interrow-fill`. */
  layerId: string;
};

const INSPECT_PRIORITY: Record<string, number> = {
  route: 0,
  row: 1,
  waste: 2,
  interrow_area: 3,
  vineyard: 4,
};

/**
 * Select mode prefers the object under the pointer.
 * `row-line` is the drawn row axis; `row-hit` is only the wide invisible buffer, so it loses to an inter-row fill.
 */
const PICK_LAYER_PRIORITY: Record<string, number> = {
  "waste-fill": 0,
  "waste-line": 1,
  "vineyard-fill": 2,
  "row-line": 3,
  "interrow-fill": 4,
  "interrow-line": 5,
  "route-line": 6,
  "route-hit": 7,
  "row-hit": 8,
};

/** Stable click order. In pick mode the first fid is the object to toggle. */
export function orderClickedFids(hits: readonly MapHit[], pick: boolean): number[] {
  const ranked = [...hits].sort((a, b) => {
    if (pick) return (PICK_LAYER_PRIORITY[a.layerId] ?? 20) - (PICK_LAYER_PRIORITY[b.layerId] ?? 20);
    return (INSPECT_PRIORITY[a.label] ?? 9) - (INSPECT_PRIORITY[b.label] ?? 9);
  });
  const fids: number[] = [];
  for (const hit of ranked) {
    if (Number.isInteger(hit.fid) && !fids.includes(hit.fid)) fids.push(hit.fid);
  }
  return fids;
}

export type RouteClickDecision =
  | { type: "toggle"; fid: number }
  | { type: "place" }
  | { type: "inspect"; fid: number | null }
  | { type: "ignore" };

function itemByFid(items: readonly FieldFeature[], fid: number): FieldFeature | undefined {
  const direct = items[fid];
  if (direct?.fid === fid) return direct;
  return items.find((item) => item.fid === fid);
}

/**
 * Map click while a route is being chosen or the start/end point is being placed.
 * In pick mode only the topmost feature counts. An allowed target is toggled.
 * An inter-row or a non-gap row axis is ignored, even when another feature sits underneath.
 * Pick mode never inspects. Placement runs when pick mode is off, or when a pick-mode
 * click missed every feature.
 */
export function decideRouteClick(
  mode: RouteClickMode,
  fids: readonly number[],
  items: readonly FieldFeature[],
): RouteClickDecision {
  if (mode.pick) {
    const fid = fids.find((id) => itemByFid(items, id) !== undefined);
    if (fid !== undefined) {
      const item = itemByFid(items, fid);
      if (item && isSelectableRouteTarget(item)) return { type: "toggle", fid };
      return { type: "ignore" };
    }
    if (mode.place) return { type: "place" };
    return { type: "ignore" };
  }
  if (mode.place) return { type: "place" };
  return { type: "inspect", fid: fids[0] ?? null };
}

/** Half the width of the strip a row's canopy blocks. Inter-rows are about 2.5 m apart. */
export const ROW_HALF_WIDTH_M = 0.6;

/** Point the walk must pass within 2 m of: a row's middle, a polygon's centre, or the point itself. */
export function targetPoint(geometry: Geometry): Metres | null {
  if (geometry.type === "Point") return [geometry.coordinates[0], geometry.coordinates[1]];
  if (geometry.type === "LineString") return alongLine(geometry.coordinates, 0.5);
  if (geometry.type === "Polygon") return centre(openRing(geometry.coordinates[0] ?? []));
  if (geometry.type === "MultiPolygon") return centre(openRing(geometry.coordinates[0]?.[0] ?? []));
  return null;
}

function openRing(ring: Position[]): Position[] {
  const first = ring[0];
  const last = ring[ring.length - 1];
  return first && last && ring.length > 1 && first[0] === last[0] && first[1] === last[1] ? ring.slice(0, -1) : ring;
}

function centre(points: Position[]): Metres | null {
  if (points.length === 0) return null;
  const sum = points.reduce((acc, [x, y]) => [acc[0] + x, acc[1] + y], [0, 0]);
  return [sum[0] / points.length, sum[1] / points.length];
}

function alongLine(points: Position[], fraction: number): Metres | null {
  if (points.length === 0) return null;
  const lengths = points.slice(1).map((point, i) => Math.hypot(point[0] - points[i][0], point[1] - points[i][1]));
  let remaining = lengths.reduce((sum, length) => sum + length, 0) * fraction;
  for (let i = 0; i < lengths.length; i++) {
    if (remaining <= lengths[i] && lengths[i] > 0) {
      const t = remaining / lengths[i];
      return [points[i][0] + (points[i + 1][0] - points[i][0]) * t, points[i][1] + (points[i + 1][1] - points[i][1]) * t];
    }
    remaining -= lengths[i];
  }
  return [points[points.length - 1][0], points[points.length - 1][1]];
}

/** A row axis widened into a solid strip, flat at both ends, so the walk stays in the inter-rows. */
export function rowStrip(line: Position[], halfWidth = ROW_HALF_WIDTH_M): Metres[] | null {
  const points = line.filter((point, i) => i === 0 || point[0] !== line[i - 1][0] || point[1] !== line[i - 1][1]);
  if (points.length < 2) return null;
  const normals = points.map((_, i) => {
    const a = points[Math.max(0, i - 1)];
    const b = points[Math.min(points.length - 1, i + 1)];
    const length = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
    return [-(b[1] - a[1]) / length, (b[0] - a[0]) / length];
  });
  const left = points.map(([x, y], i): Metres => [x + normals[i][0] * halfWidth, y + normals[i][1] * halfWidth]);
  const right = points.map(([x, y], i): Metres => [x - normals[i][0] * halfWidth, y - normals[i][1] * halfWidth]);
  return [...left, ...right.reverse()];
}

/** Exterior ring of one canopy polygon, open, in the same metres as the planner. */
function canopyRings(geometry: Geometry): Metres[][] {
  const rings =
    geometry.type === "Polygon"
      ? [geometry.coordinates[0] ?? []]
      : geometry.type === "MultiPolygon"
        ? geometry.coordinates.map((polygon) => polygon[0] ?? [])
        : [];
  return rings.flatMap((ring) => {
    const open = openRing(ring);
    return open.length >= 3 ? [open.map(([x, y]): Metres => [x, y])] : [];
  });
}

/**
 * Request for the backend planner. Geometry must be in EPSG:32635 metres, indexed by `fid`.
 * Every row axis in `items` is an obstacle strip. Every canopy polygon is ground the walk
 * must not cross. The selected objects are the targets.
 * Pass `featuresInBlock` when the walk should stay on one vineyard.
 */
export function buildRoutePlanRequest(
  routeType: RouteTypeId,
  items: readonly FieldFeature[],
  geometries: ReadonlyMap<number, Geometry>,
  targetFids: readonly number[],
  start: readonly [number, number],
): RoutePlanRequest {
  const obstacles = items.flatMap((item) => {
    const geometry = geometries.get(item.fid);
    if (item.label !== "row" || geometry?.type !== "LineString") return [];
    const strip = rowStrip(geometry.coordinates);
    return strip ? [strip] : [];
  });
  const canopies = items.flatMap((item) => {
    const geometry = geometries.get(item.fid);
    if (item.label !== "vineyard" || !geometry) return [];
    return canopyRings(geometry);
  });
  const targets = [...targetFids]
    .sort((a, b) => a - b)
    .flatMap((fid) => {
      const item = itemByFid(items, fid);
      const geometry = geometries.get(fid);
      const point = item && geometry && isSelectableRouteTarget(item) ? targetPoint(geometry) : null;
      return point ? [point] : [];
    });
  return { routeType, obstacles, canopies, start: [start[0], start[1]], targets };
}
