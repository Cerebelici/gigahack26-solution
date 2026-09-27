import { sampleResult } from "../src/features/map/fixture";
import { buildFieldData, fromLngLat, toLngLat } from "../src/features/map/project";
import { ROUTE_START_EPSG32635 } from "../src/features/projects/routeTypes";
import {
  buildRoutePlanRequest,
  decideRouteClick,
  featuresInBlock,
  isRowGap,
  isSelectableRouteTarget,
  orderClickedFids,
  ROW_HALF_WIDTH_M,
  routeTargetFids,
  rowStrip,
  targetPoint,
} from "../src/features/projects/routeTargets";
import type { Geometry } from "geojson";

function eq(actual: unknown, expected: unknown, message: string): void {
  const left = JSON.stringify(actual);
  const right = JSON.stringify(expected);
  if (left !== right) throw new Error(`${message}\nexpected ${right}\nactual   ${left}`);
}

const data = buildFieldData(sampleResult);
// buildFieldData numbers features in order, and every fixture feature has a geometry.
const geometries = new Map<number, Geometry>(
  sampleResult.features.features.map((feature, fid) => [fid, feature.geometry as Geometry]),
);
const near = (actual: readonly number[] | null | undefined, expected: readonly number[], message: string) => {
  if (!actual || actual.some((value, i) => Math.abs(value - expected[i]) > 1e-6)) {
    throw new Error(`${message}\nexpected ${JSON.stringify(expected)}\nactual   ${JSON.stringify(actual)}`);
  }
};
const gaps = data.items.filter(isRowGap);
const waste = data.items.filter((item) => item.label === "waste");

eq(
  gaps.map((item) => item.rowId),
  ["V01-R03", "V02-R03"],
  "disrupted rows are the row gaps",
);
eq(routeTargetFids("waste", data.items), waste.map((item) => item.fid), "waste route");
eq(routeTargetFids("inspection", data.items), gaps.map((item) => item.fid), "inspection route");

const wasteFid = waste[0]?.fid ?? -1;
const gapFid = gaps[0]?.fid ?? -1;
const plan = buildRoutePlanRequest("waste", data.items, geometries, [wasteFid, gapFid], [629500.12, 5220200.34]);
eq(plan.routeType, "waste", "route type");
eq(plan.start, [629500.12, 5220200.34], "start");
eq(plan.obstacles.length, data.items.filter((item) => item.label === "row").length, "every row axis is an obstacle");
eq(
  plan.canopies.length,
  data.items.filter((item) => item.label === "vineyard").length,
  "every canopy is ground the walk must not cross",
);
eq(
  plan.targets,
  [gapFid, wasteFid].sort((a, b) => a - b).map((fid) => targetPoint(geometries.get(fid) as Geometry)),
  "targets are points, sorted by fid",
);

const gapLine = geometries.get(gapFid);
if (gapLine?.type !== "LineString") throw new Error("row gap is not a line");
const [[ax, ay], [bx, by]] = [gapLine.coordinates[0], gapLine.coordinates[gapLine.coordinates.length - 1]];
near(targetPoint(gapLine), [(ax + bx) / 2, (ay + by) / 2], "a row target is the middle of the row");

const strip = rowStrip([[0, 0], [10, 0]]);
eq(strip, [[0, ROW_HALF_WIDTH_M], [10, ROW_HALF_WIDTH_M], [10, -ROW_HALF_WIDTH_M], [0, -ROW_HALF_WIDTH_M]], "row strip");
eq(rowStrip([[1, 1], [1, 1]]), null, "a row without length has no strip");
near(targetPoint({ type: "Polygon", coordinates: [[[0, 0], [4, 0], [4, 2], [0, 2], [0, 0]]] }), [2, 1], "box centre");

const regular = data.items.find((item) => item.label === "row" && item.props.row_structure === "regular");
const unassessable = data.items.find((item) => item.label === "row" && item.props.row_structure === "unassessable");
const canopy = data.items.find((item) => item.label === "vineyard");
if (!regular || !unassessable || !canopy) throw new Error("fixture is missing a regular row, an unassessable row, or a canopy");

const interrow = data.items.find((item) => item.label === "interrow_area");
if (!interrow) throw new Error("fixture is missing an inter-row");
const rowAxis = regular;
const gap = gaps[0];
if (!gap) throw new Error("fixture is missing a disrupted row");
eq(isSelectableRouteTarget(interrow), false, "inter-row is not a manual target");
eq(isSelectableRouteTarget(rowAxis), false, "intact row axis is not a manual target");
eq(isSelectableRouteTarget(unassessable), false, "unassessable row axis is not a manual target");
eq(isSelectableRouteTarget(gap), true, "disrupted row stays a manual target");
eq(isSelectableRouteTarget(waste[0]), true, "waste stays a manual target");
eq(isSelectableRouteTarget(canopy), true, "canopy stays a manual target");
eq(
  orderClickedFids(
    [
      { fid: rowAxis.fid, label: "row", layerId: "row-hit" },
      { fid: interrow.fid, label: "interrow_area", layerId: "interrow-fill" },
    ],
    true,
  )[0],
  interrow.fid,
  "inter-row fill wins over the row-hit buffer",
);
eq(
  orderClickedFids(
    [
      { fid: interrow.fid, label: "interrow_area", layerId: "interrow-fill" },
      { fid: rowAxis.fid, label: "row", layerId: "row-line" },
    ],
    true,
  )[0],
  rowAxis.fid,
  "drawn row axis wins over the inter-row",
);
eq(
  orderClickedFids(
    [
      { fid: interrow.fid, label: "interrow_area", layerId: "interrow-fill" },
      { fid: rowAxis.fid, label: "row", layerId: "row-line" },
    ],
    false,
  )[0],
  rowAxis.fid,
  "inspect still prefers the row",
);

const withArea = buildRoutePlanRequest(
  "waste",
  data.items,
  geometries,
  [rowAxis.fid, interrow.fid, gapFid],
  [629500, 5220200],
);
eq(
  withArea.targets,
  [targetPoint(gapLine)],
  "payload keeps the disrupted row and drops the inter-row and intact axis",
);

eq(decideRouteClick({ pick: true, place: true }, [gapFid], data.items), { type: "toggle", fid: gapFid }, "disrupted row toggles");
eq(
  decideRouteClick({ pick: true, place: true }, [gapFid, interrow.fid], data.items),
  { type: "toggle", fid: gapFid },
  "drawn disrupted row wins over the inter-row underneath",
);
eq(
  decideRouteClick({ pick: true, place: true }, [interrow.fid, gapFid], data.items),
  { type: "ignore" },
  "inter-row on top does nothing",
);
eq(
  decideRouteClick({ pick: true, place: true }, [regular.fid, wasteFid], data.items),
  { type: "ignore" },
  "intact row axis does nothing",
);
eq(
  decideRouteClick({ pick: true, place: false }, [unassessable.fid], data.items),
  { type: "ignore" },
  "unassessable row axis does nothing",
);
eq(
  decideRouteClick({ pick: true, place: true }, [canopy.fid], data.items),
  { type: "toggle", fid: canopy.fid },
  "canopy toggles",
);
eq(
  decideRouteClick({ pick: true, place: false }, [wasteFid], data.items),
  { type: "toggle", fid: wasteFid },
  "waste toggles without opening info",
);
eq(decideRouteClick({ pick: true, place: true }, [], data.items), { type: "place" }, "empty click places");
eq(decideRouteClick({ pick: true, place: false }, [], data.items), { type: "ignore" }, "empty pick click does not inspect");
eq(decideRouteClick({ pick: false, place: true }, [canopy.fid], data.items), { type: "place" }, "place ignores features");
eq(
  decideRouteClick({ pick: false, place: false }, [interrow.fid], data.items),
  { type: "inspect", fid: interrow.fid },
  "looking at an inter-row",
);
eq(
  decideRouteClick({ pick: false, place: false }, [regular.fid], data.items),
  { type: "inspect", fid: regular.fid },
  "looking at a row axis",
);

const withCanopy = buildRoutePlanRequest("waste", data.items, geometries, [canopy.fid], [629500, 5220200]);
eq(withCanopy.targets, [targetPoint(geometries.get(canopy.fid) as Geometry)], "a canopy target is its centre");
eq(
  decideRouteClick({ pick: false, place: false }, [wasteFid], data.items),
  { type: "inspect", fid: wasteFid },
  "inspect",
);

const v01 = featuresInBlock(data.items, "V01");
eq(
  routeTargetFids("inspection", v01),
  gaps.filter((item) => item.block === "V01").map((item) => item.fid),
  "a vineyard keeps its own row gaps",
);
eq(routeTargetFids("waste", v01), [], "a vineyard without waste has no waste targets");
const v01Plan = buildRoutePlanRequest("inspection", v01, geometries, routeTargetFids("inspection", v01), [629500, 5220200]);
eq(
  v01Plan.obstacles.length,
  data.items.filter((item) => item.label === "row" && item.block === "V01").length,
  "obstacles are the rows of that vineyard",
);
eq(
  v01Plan.canopies.length,
  v01.filter((item) => item.label === "vineyard").length,
  "canopies are the vines of that vineyard",
);
eq(featuresInBlock(data.items, null).length, data.items.length, "no vineyard keeps the whole field");

const [x, y] = ROUTE_START_EPSG32635;
const roundTrip = fromLngLat(toLngLat([x, y]));
if (Math.hypot(roundTrip[0] - x, roundTrip[1] - y) > 0.05) {
  throw new Error(`lng/lat round trip drifted: ${roundTrip.join(", ")}`);
}
