import type { Feature, FeatureCollection, Geometry, MultiLineString, Point, Position } from "geojson";
import type { ExpressionSpecification, GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import { MAP_COLORS } from "./palette";
import type { FieldData, LngLatPair } from "./types";

export type RevealPhase = "scan" | "rows" | "polygons" | "routes" | "done";

export interface RevealCount {
  done: number;
  total: number;
}

export interface RevealProgress {
  phase: RevealPhase;
  /** 0–1 over the whole reveal. */
  fraction: number;
  rows: RevealCount;
  polygons: RevealCount;
  routes: RevealCount;
}

export interface RevealHandle {
  /** Jump to the final state, then report "done". */
  skip(): void;
  /** Stop and remove the temporary layers without reporting. */
  cancel(): void;
}

interface RevealOptions {
  /** Animated strokes are drawn under this layer so the selection stays on top. */
  beforeId?: string;
  onProgress?: (progress: RevealProgress) => void;
  onDone?: () => void;
}

export const PENDING_REVEAL: RevealProgress = {
  phase: "scan",
  fraction: 0,
  rows: { done: 0, total: 0 },
  polygons: { done: 0, total: 0 },
  routes: { done: 0, total: 0 },
};

export function revealShare(count: RevealCount): number {
  return count.total === 0 ? 0 : count.done / count.total;
}

const FIELD = "field";
const REVEAL_KEY = "reveal";
const FLASH_KEY = "flash";
const TRACE = "reveal-trace";
const SCAN = "reveal-scan";
const TRACE_LAYERS = ["reveal-flash-fill", "reveal-flash-line", "reveal-trace-glow", "reveal-trace-line", "reveal-trace-spark"];
const SCAN_LAYERS = ["reveal-scan-band", "reveal-scan-grid", "reveal-scan-glow", "reveal-scan-beam"];

const ROW_LABELS = ["row"];
const POLYGON_LABELS = ["vineyard", "interrow_area", "waste"];
const ROUTE_LABELS = ["route"];

// Milliseconds. Spreads are fixed, so the total stays near 4.5 s whatever the feature count.
const T = {
  scan: 900,
  scanFade: 450,
  rowsAt: 650,
  rowsSpread: 1250,
  rowDraw: 520,
  polygonsLead: 350,
  polygonsSpread: 1300,
  polygonDraw: 780,
  flash: 360,
  routesLead: 250,
  routeDraw: 950,
};
const TRACE_SHARE = 0.55;
const SCAN_GRID = 12;
const SCAN_BAND = 0.14;

const TRACE_COLORS: Record<string, string> = {
  row: MAP_COLORS.row,
  vineyard: MAP_COLORS.canopyLine,
  interrow_area: MAP_COLORS.interrowLine,
  waste: MAP_COLORS.waste,
  route: MAP_COLORS.route,
};

const TRACE_WIDTHS: Record<string, number> = { row: 2.4, route: 3, waste: 2 };

/** Multiplies a paint opacity by the feature's reveal state. Features the reveal has not reached stay hidden. */
export function withReveal(value: number | ExpressionSpecification): ExpressionSpecification {
  return ["*", value, ["coalesce", ["feature-state", REVEAL_KEY], 0]];
}

type Kind = "row" | "polygon" | "route";

interface TraceProps {
  color: string;
  width: number;
  o: number;
}

interface Path {
  points: Position[];
  cumulative: Float64Array;
  out: Position[];
  head: Position;
  segment: number;
}

interface Track {
  fid: number;
  kind: Kind;
  start: number;
  duration: number;
  paths: Path[];
  line: Feature<MultiLineString, TraceProps>;
  spark: Feature<Point, TraceProps>;
  fill: number;
  flash: number;
  done: boolean;
}

const clamp01 = (value: number) => (value < 0 ? 0 : value > 1 ? 1 : value);
const easeOut = (t: number) => 1 - (1 - t) ** 3;
const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

function pathsOf(geometry: Geometry): Position[][] {
  switch (geometry.type) {
    case "LineString":
      return [geometry.coordinates];
    case "MultiLineString":
    case "Polygon":
      return geometry.coordinates;
    case "MultiPolygon":
      return geometry.coordinates.flat();
    default:
      return [];
  }
}

function makePath(points: Position[]): Path {
  const cumulative = new Float64Array(points.length);
  const kx = Math.cos((points[0][1] * Math.PI) / 180);
  for (let i = 1; i < points.length; i++) {
    const dx = (points[i][0] - points[i - 1][0]) * kx;
    const dy = points[i][1] - points[i - 1][1];
    cumulative[i] = cumulative[i - 1] + Math.hypot(dx, dy);
  }
  return { points, cumulative, out: [], head: [points[0][0], points[0][1]], segment: 0 };
}

/** Rewrites `path.out` in place as the first `fraction` of the path. Fractions only grow within one reveal. */
function trimPath(path: Path, fraction: number) {
  const { points, cumulative, out, head } = path;
  const last = points.length - 1;
  const target = cumulative[last] * fraction;
  let k = path.segment;
  while (k < last - 1 && cumulative[k + 1] <= target) k++;
  path.segment = k;
  const span = cumulative[k + 1] - cumulative[k];
  const t = span > 0 ? clamp01((target - cumulative[k]) / span) : 1;
  head[0] = points[k][0] + (points[k + 1][0] - points[k][0]) * t;
  head[1] = points[k][1] + (points[k + 1][1] - points[k][1]) * t;
  out.length = 0;
  for (let i = 0; i <= k; i++) out.push(points[i]);
  out.push(head);
}

/** Position along the top-to-bottom sweep of the image, 0 at the top edge and 1 at the bottom. */
function sweepAxis([tl, tr, br, bl]: FieldData["imageCorners"]): (point: Position) => number {
  const top = [(tl[0] + tr[0]) / 2, (tl[1] + tr[1]) / 2];
  const bottom = [(bl[0] + br[0]) / 2, (bl[1] + br[1]) / 2];
  const kx = Math.cos((top[1] * Math.PI) / 180);
  const ax = (bottom[0] - top[0]) * kx;
  const ay = bottom[1] - top[1];
  const length2 = ax * ax + ay * ay || 1;
  return ([x, y]) => (((x - top[0]) * kx) * ax + (y - top[1]) * ay) / length2;
}

function centre(points: Position[]): Position {
  let x = 0;
  let y = 0;
  for (const point of points) {
    x += point[0];
    y += point[1];
  }
  return [x / points.length, y / points.length];
}

function stagger(count: number, spread: number): number {
  if (count <= 1) return 0;
  return (spread * Math.min(1, (count - 1) / 12)) / (count - 1);
}

function buildTracks(data: FieldData, labels: string[], kind: Kind, at: number, spread: number, duration: number): Track[] {
  const sweep = sweepAxis(data.imageCorners);
  const found: Array<{ fid: number; label: string; paths: Path[]; key: number }> = [];
  for (const feature of data.mapFeatures.features) {
    const label = String(feature.properties?.label ?? "");
    if (!feature.geometry || !labels.includes(label)) continue;
    const paths = pathsOf(feature.geometry)
      .filter((points) => points.length >= 2)
      .map(makePath);
    if (paths.length === 0) continue;
    found.push({ fid: Number(feature.properties?.fid), label, paths, key: sweep(centre(paths[0].points)) });
  }
  found.sort((a, b) => a.key - b.key || a.fid - b.fid);

  const step = stagger(found.length, spread);
  return found.map(({ fid, label, paths }, index) => {
    const props = (): TraceProps => ({ color: TRACE_COLORS[label] ?? MAP_COLORS.row, width: TRACE_WIDTHS[label] ?? 1.5, o: 1 });
    return {
      fid,
      kind,
      start: at + index * step,
      duration,
      paths,
      line: { type: "Feature", properties: props(), geometry: { type: "MultiLineString", coordinates: paths.map((p) => p.out) } },
      spark: { type: "Feature", properties: props(), geometry: { type: "Point", coordinates: paths[0].head } },
      fill: 0,
      flash: 0,
      done: false,
    };
  });
}

function lastStart(tracks: Track[], fallback: number): number {
  return tracks.length ? tracks[tracks.length - 1].start : fallback;
}

function lerp(a: LngLatPair, b: LngLatPair, t: number): Position {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

function addRevealLayers(map: MapLibreMap, beforeId: string | undefined) {
  map.addSource(TRACE, { type: "geojson", data: EMPTY });
  map.addSource(SCAN, { type: "geojson", data: EMPTY });
  const polygons: ExpressionSpecification = ["in", ["get", "label"], ["literal", POLYGON_LABELS]];
  const flash: ExpressionSpecification = ["coalesce", ["feature-state", FLASH_KEY], 0];
  const notPoint: ExpressionSpecification = ["!=", ["geometry-type"], "Point"];

  map.addLayer(
    {
      id: "reveal-flash-fill",
      type: "fill",
      source: FIELD,
      filter: polygons,
      paint: { "fill-color": MAP_COLORS.halo, "fill-opacity": ["*", 0.35, flash] },
    },
    beforeId,
  );
  map.addLayer(
    {
      id: "reveal-flash-line",
      type: "line",
      source: FIELD,
      filter: polygons,
      paint: { "line-color": MAP_COLORS.scan, "line-width": 4, "line-blur": 3, "line-opacity": flash },
    },
    beforeId,
  );
  map.addLayer(
    {
      id: "reveal-trace-glow",
      type: "line",
      source: TRACE,
      filter: notPoint,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": ["get", "color"],
        "line-width": ["*", ["get", "width"], 3.2],
        "line-blur": 5,
        "line-opacity": ["*", 0.55, ["get", "o"]],
      },
    },
    beforeId,
  );
  map.addLayer(
    {
      id: "reveal-trace-line",
      type: "line",
      source: TRACE,
      filter: notPoint,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": ["get", "color"], "line-width": ["get", "width"], "line-opacity": ["get", "o"] },
    },
    beforeId,
  );
  map.addLayer(
    {
      id: "reveal-trace-spark",
      type: "circle",
      source: TRACE,
      filter: ["==", ["geometry-type"], "Point"],
      paint: {
        "circle-color": MAP_COLORS.halo,
        "circle-radius": ["+", 1.5, ["get", "width"]],
        "circle-blur": 0.6,
        "circle-opacity": ["get", "o"],
      },
    },
    beforeId,
  );

  const kind = (name: string): ExpressionSpecification => ["==", ["get", "kind"], name];
  map.addLayer({
    id: "reveal-scan-band",
    type: "fill",
    source: SCAN,
    filter: kind("band"),
    paint: { "fill-color": MAP_COLORS.scan, "fill-opacity": ["get", "o"] },
  });
  map.addLayer({
    id: "reveal-scan-grid",
    type: "line",
    source: SCAN,
    filter: kind("grid"),
    paint: { "line-color": MAP_COLORS.scan, "line-width": 1, "line-opacity": ["get", "o"] },
  });
  map.addLayer({
    id: "reveal-scan-glow",
    type: "line",
    source: SCAN,
    filter: kind("beam"),
    paint: { "line-color": MAP_COLORS.scan, "line-width": 22, "line-blur": 16, "line-opacity": ["*", 0.7, ["get", "o"]] },
  });
  map.addLayer({
    id: "reveal-scan-beam",
    type: "line",
    source: SCAN,
    filter: kind("beam"),
    paint: { "line-color": MAP_COLORS.halo, "line-width": 2, "line-opacity": ["get", "o"] },
  });
}

function removeRevealLayers(map: MapLibreMap) {
  for (const id of [...TRACE_LAYERS, ...SCAN_LAYERS]) if (map.getLayer(id)) map.removeLayer(id);
  for (const id of [TRACE, SCAN]) if (map.getSource(id)) map.removeSource(id);
}

function scanFeatures(corners: FieldData["imageCorners"], sweep: number, fade: number): FeatureCollection {
  const [tl, tr, br, bl] = corners;
  const at = (u: number, v: number) => lerp(lerp(tl, tr, u) as LngLatPair, lerp(bl, br, u) as LngLatPair, v);
  const grid: Position[][] = [];
  for (let i = 0; i <= SCAN_GRID; i++) {
    const u = i / SCAN_GRID;
    grid.push([at(u, 0), at(u, sweep)]);
    if (u <= sweep) grid.push([at(0, u), at(1, u)]);
  }
  const features: Feature[] = [
    { type: "Feature", properties: { kind: "grid", o: 0.32 * fade }, geometry: { type: "MultiLineString", coordinates: grid } },
    { type: "Feature", properties: { kind: "beam", o: fade }, geometry: { type: "LineString", coordinates: [at(0, sweep), at(1, sweep)] } },
  ];
  for (let k = 0; k < 4; k++) {
    const from = Math.max(0, sweep - (SCAN_BAND * (k + 1)) / 4);
    const to = Math.max(0, sweep - (SCAN_BAND * k) / 4);
    if (to <= from) continue;
    features.push({
      type: "Feature",
      properties: { kind: "band", o: (0.2 - k * 0.045) * fade },
      geometry: { type: "Polygon", coordinates: [[at(0, from), at(1, from), at(1, to), at(0, to), at(0, from)]] },
    });
  }
  return { type: "FeatureCollection", features };
}

/**
 * States are left at their final values when the reveal ends. Switch the real layers back to plain opacity only
 * after the next render: MapLibre throws if a feature-state change reaches a layer whose paint no longer uses it.
 *
 * Staged reveal of the field annotations: scan sweep, rows growing, polygons traced then filled, routes last.
 * The real layers stay in place and queryable; `withReveal` opacity plus per-feature state hides what is not drawn yet.
 */
export function playReveal(map: MapLibreMap, data: FieldData, { beforeId, onProgress, onDone }: RevealOptions = {}): RevealHandle {
  const rows = buildTracks(data, ROW_LABELS, "row", T.rowsAt, T.rowsSpread, T.rowDraw);
  const rowsEnd = rows.length ? lastStart(rows, T.rowsAt) + T.rowDraw : T.rowsAt;
  const polygonsAt = rows.length ? rowsEnd - T.polygonsLead : T.rowsAt;
  const polygons = buildTracks(data, POLYGON_LABELS, "polygon", polygonsAt, T.polygonsSpread, T.polygonDraw);
  const polygonsEnd = polygons.length ? lastStart(polygons, polygonsAt) + T.polygonDraw : polygonsAt;
  const routesAt = polygons.length ? polygonsEnd - T.routesLead : polygonsEnd;
  const routes = buildTracks(data, ROUTE_LABELS, "route", routesAt, T.polygonsSpread / 2, T.routeDraw);
  const routesEnd = routes.length ? lastStart(routes, routesAt) + T.routeDraw : routesAt;
  const total = Math.max(T.scan + T.scanFade, rowsEnd, polygonsEnd + T.flash, routesEnd);
  const tracks = [...rows, ...polygons, ...routes];

  const counts = {
    rows: { done: 0, total: rows.length },
    polygons: { done: 0, total: polygons.length },
    routes: { done: 0, total: routes.length },
  };
  const countFor = (kind: Kind) => (kind === "row" ? counts.rows : kind === "polygon" ? counts.polygons : counts.routes);

  // States from the previous reveal would show everything at once.
  map.removeFeatureState({ source: FIELD });
  addRevealLayers(map, beforeId);
  const traceSource = map.getSource<GeoJSONSource>(TRACE);
  const scanSource = map.getSource<GeoJSONSource>(SCAN);
  const trace: FeatureCollection = { type: "FeatureCollection", features: [] };
  const flashTail = T.flash / T.polygonDraw;

  let started = performance.now();
  let raf = 0;
  let traceShown = false;
  let scanShown = true;
  let phase: RevealPhase = "scan";
  let lastReport = "";
  let finished = false;

  const setState = (fid: number, state: Record<string, number>) => map.setFeatureState({ source: FIELD, id: fid }, state);

  function report(fraction: number) {
    const key = `${phase}|${counts.rows.done}|${counts.polygons.done}|${counts.routes.done}|${Math.floor(fraction * 60)}`;
    if (key === lastReport) return;
    lastReport = key;
    onProgress?.({ phase, fraction, rows: { ...counts.rows }, polygons: { ...counts.polygons }, routes: { ...counts.routes } });
  }

  function drawScan(elapsed: number) {
    if (!scanShown) return;
    if (elapsed >= T.scan + T.scanFade) {
      scanSource?.setData(EMPTY);
      scanShown = false;
      return;
    }
    const sweep = easeInOut(clamp01(elapsed / T.scan));
    const fade = elapsed <= T.scan ? 1 : 1 - (elapsed - T.scan) / T.scanFade;
    scanSource?.setData(scanFeatures(data.imageCorners, sweep, fade));
  }

  function drawLine(track: Track, local: number) {
    if (local >= 1) {
      track.done = true;
      countFor(track.kind).done++;
      setState(track.fid, { [REVEAL_KEY]: 1 });
      return;
    }
    const grown = easeOut(local);
    for (const path of track.paths) trimPath(path, grown);
    trace.features.push(track.line, track.spark);
  }

  function drawPolygon(track: Track, local: number) {
    const traced = clamp01(local / TRACE_SHARE);
    const fill = easeInOut(clamp01((local - TRACE_SHARE) / (1 - TRACE_SHARE)));
    const flashAt = (local - 0.85) / (0.15 + flashTail);
    const flash = flashAt <= 0 || flashAt >= 1 ? 0 : Math.sin(flashAt * Math.PI);

    if (fill < 1) {
      for (const path of track.paths) trimPath(path, easeOut(traced));
      track.line.properties.o = 1 - fill;
      track.spark.properties.o = 1 - traced;
      trace.features.push(track.line);
      if (traced < 1) trace.features.push(track.spark);
    }
    if (fill !== track.fill || flash !== track.flash) {
      if (fill >= 1 && track.fill < 1) countFor(track.kind).done++;
      track.fill = fill;
      track.flash = flash;
      setState(track.fid, { [REVEAL_KEY]: fill, [FLASH_KEY]: flash });
    }
    if (fill >= 1 && flashAt >= 1) track.done = true;
  }

  function finish() {
    if (finished) return;
    finished = true;
    cancelAnimationFrame(raf);
    for (const track of tracks) {
      if (!track.done || track.flash !== 0) setState(track.fid, { [REVEAL_KEY]: 1, [FLASH_KEY]: 0 });
    }
    removeRevealLayers(map);
    counts.rows.done = counts.rows.total;
    counts.polygons.done = counts.polygons.total;
    counts.routes.done = counts.routes.total;
    phase = "done";
    report(1);
    onDone?.();
  }

  function frame(now: number) {
    const elapsed = now - started;
    drawScan(elapsed);

    trace.features.length = 0;
    for (const track of tracks) {
      if (track.done) continue;
      const local = (elapsed - track.start) / track.duration;
      if (local <= 0) continue;
      if (track.kind === "polygon") drawPolygon(track, local);
      else drawLine(track, local);
    }
    if (trace.features.length > 0 || traceShown) {
      traceSource?.setData(trace);
      traceShown = trace.features.length > 0;
    }

    if (elapsed >= T.rowsAt) {
      if (counts.rows.done < counts.rows.total) phase = "rows";
      else if (counts.polygons.done < counts.polygons.total) phase = "polygons";
      else if (counts.routes.done < counts.routes.total) phase = "routes";
    }

    if (elapsed >= total && tracks.every((track) => track.done)) {
      finish();
      return;
    }
    report(Math.min(1, elapsed / total));
    raf = requestAnimationFrame(frame);
  }

  report(0);
  started = performance.now();
  raf = requestAnimationFrame(frame);

  return {
    skip: finish,
    cancel() {
      if (finished) return;
      finished = true;
      cancelAnimationFrame(raf);
      removeRevealLayers(map);
    },
  };
}
