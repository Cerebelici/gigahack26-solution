import { sampleResult } from "../src/features/map/fixture";
import { buildFieldData, fromLngLat, toLngLat } from "../src/features/map/project";
import { ROUTE_START_EPSG32635 } from "../src/features/projects/routeTypes";
import {
  buildRoutePlanRequest,
  decideRouteClick,
  isRowGap,
  isSelectableRouteTarget,
  orderClickedFids,
  routeTargetFids,
} from "../src/features/projects/routeTargets";

function eq(actual: unknown, expected: unknown, message: string): void {
  const left = JSON.stringify(actual);
  const right = JSON.stringify(expected);
  if (left !== right) throw new Error(`${message}\nexpected ${right}\nactual   ${left}`);
}

const data = buildFieldData(sampleResult);
const gaps = data.items.filter(isRowGap);
const waste = data.items.filter((item) => item.label === "waste");

eq(
  gaps.map((item) => item.rowId),
  ["V01-R03", "V02-R03"],
  "disrupted rows are the row gaps",
);
eq(routeTargetFids("waste", data.items), waste.map((item) => item.fid), "waste route");
eq(routeTargetFids("inspection", data.items), gaps.map((item) => item.fid), "inspection route");
eq(
  routeTargetFids("full", data.items),
  [...gaps, ...waste].map((item) => item.fid),
  "full route",
);

const wasteFid = waste[0]?.fid ?? -1;
const gapFid = gaps[0]?.fid ?? -1;
const plan = buildRoutePlanRequest("waste", data.items, [wasteFid, gapFid], [629500.12, 5220200.34]);
eq(plan.routeType, "waste", "route type");
eq(plan.start, [629500.12, 5220200.34], "start");
eq(plan.end, [629500.12, 5220200.34], "end matches start");
eq(
  plan.targets.map((target) => target.fid),
  [gapFid, wasteFid].sort((a, b) => a - b),
  "targets sorted by fid",
);
eq(plan.targets.find((target) => target.fid === gapFid)?.label, "row", "row gap label");
eq(plan.targets.find((target) => target.fid === wasteFid)?.label, "waste", "waste label");
eq(plan.targets.find((target) => target.fid === gapFid)?.rowId, "V01-R03", "row id");

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

const withArea = buildRoutePlanRequest("waste", data.items, [rowAxis.fid, interrow.fid, gapFid], [629500, 5220200]);
eq(
  withArea.targets.map((target) => target.fid),
  [gapFid],
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

const withCanopy = buildRoutePlanRequest("waste", data.items, [canopy.fid], [629500, 5220200]);
eq(withCanopy.targets[0]?.label, "vineyard", "canopy label");
eq(withCanopy.targets[0]?.vineyardId, canopy.block, "canopy block");
eq(withCanopy.targets[0]?.rowId, null, "canopy has no row");
eq(
  decideRouteClick({ pick: false, place: false }, [wasteFid], data.items),
  { type: "inspect", fid: wasteFid },
  "inspect",
);

const [x, y] = ROUTE_START_EPSG32635;
const roundTrip = fromLngLat(toLngLat([x, y]));
if (Math.hypot(roundTrip[0] - x, roundTrip[1] - y) > 0.05) {
  throw new Error(`lng/lat round trip drifted: ${roundTrip.join(", ")}`);
}
