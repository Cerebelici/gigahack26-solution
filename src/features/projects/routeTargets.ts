import type { FieldFeature } from "../map/types";
import type { RoutePlanRequest, RoutePlanTarget } from "../../types/project";
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
  if (routeType === "waste") return isWaste(item);
  if (routeType === "inspection") return isRowGap(item);
  return isWaste(item) || isRowGap(item);
}

export function routeTargetFids(routeType: RouteTypeId, items: readonly FieldFeature[]): number[] {
  return items.filter((item) => matchesRouteType(routeType, item)).map((item) => item.fid);
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

function annotationId(props: Record<string, unknown>): string | null {
  const value = props.id;
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed ? trimmed : null;
  }
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

function targetRef(item: FieldFeature): RoutePlanTarget {
  return {
    fid: item.fid,
    label: item.label,
    vineyardId: item.block || null,
    rowId: item.rowId,
    id: annotationId(item.props),
  };
}

export function buildRoutePlanRequest(
  routeType: RouteTypeId,
  items: readonly FieldFeature[],
  targetFids: readonly number[],
  start: readonly [number, number],
): RoutePlanRequest {
  const targets = [...targetFids]
    .sort((a, b) => a - b)
    .flatMap((fid) => {
      const item = itemByFid(items, fid);
      return item && isSelectableRouteTarget(item) ? [targetRef(item)] : [];
    });
  const point: [number, number] = [start[0], start[1]];
  return {
    routeType,
    start: point,
    end: [point[0], point[1]],
    targets,
  };
}
