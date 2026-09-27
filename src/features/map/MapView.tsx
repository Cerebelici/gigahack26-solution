import { useEffect, useRef, useState } from "react";
import type { Feature, FeatureCollection, MultiPolygon, Polygon } from "geojson";
import {
  Map as MapLibreMap,
  Marker,
  type GeoJSONSource,
  setWorkerUrl,
  type ExpressionSpecification,
  type FitBoundsOptions,
  type StyleSpecification,
} from "maplibre-gl";
// `?worker&url` bundles the worker's import of maplibre-gl-shared.mjs; plain `?url` breaks production builds.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";

setWorkerUrl(maplibreWorkerUrl);
import { authorizeApiRequest } from "../../api/client";
import { prefersReducedMotion } from "../../lib/motion";
import { orderClickedFids } from "../projects/routeTargets";
import { FLOW_DASH, HALO_OPACITY, HALO_WIDTH, startAmbientMotion, type AmbientMotion } from "./mapMotion";
import { MAP_COLORS } from "./palette";
import { blockBounds } from "./project";
import { playReveal, withReveal, type RevealHandle, type RevealProgress } from "./revealAnimation";
import type { FieldData, LngLatPair } from "./types";

const INTERACTIVE_LAYERS = [
  "route-hit",
  "row-hit",
  "row-line",
  "waste-fill",
  "interrow-fill",
  "interrow-line",
  "vineyard-fill",
];

const DIMMABLE: Array<[layer: string, property: "fill-opacity" | "line-opacity", base: number]> = [
  ["vineyard-fill", "fill-opacity", 0.4],
  ["vineyard-line", "line-opacity", 0.7],
  ["interrow-fill", "fill-opacity", 0.42],
  ["interrow-line", "line-opacity", 0.8],
  ["waste-fill", "fill-opacity", 0.14],
  ["waste-glow", "line-opacity", 0.45],
  ["waste-line", "line-opacity", 1],
  ["row-glow", "line-opacity", 0.35],
  ["row-line", "line-opacity", 0.95],
  ["route-glow", "line-opacity", 0.5],
  ["route-line", "line-opacity", 0.95],
  ["route-flow", "line-opacity", 0.85],
];

// Data-driven values do not interpolate: a transition would show the old opacity for its whole duration.
const NO_TRANSITION = { duration: 0, delay: 0 };

const BASE_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": MAP_COLORS.background } }],
};

const byLabel = (label: string): ExpressionSpecification => ["==", ["get", "label"], label];

const EMPTY_COLLECTION: FeatureCollection = { type: "FeatureCollection", features: [] };

/** A planned walk in lng/lat, with the targets it could not reach. */
export type PlannedRoute = { line: LngLatPair[]; unreachable: LngLatPair[] };

/** Cadastral parcel outline in WGS84 longitude, latitude. */
export type CadastralFeature = Feature<Polygon | MultiPolygon>;

function cadastralData(feature: CadastralFeature | null): FeatureCollection {
  if (!feature) return EMPTY_COLLECTION;
  return { type: "FeatureCollection", features: [feature] };
}

function showCadastral(map: MapLibreMap, feature: CadastralFeature | null) {
  map.getSource<GeoJSONSource>("cadastral")?.setData(cadastralData(feature));
}

function geometryBounds(geometry: Polygon | MultiPolygon): [LngLatPair, LngLatPair] | null {
  const box: [number, number, number, number] = [Infinity, Infinity, -Infinity, -Infinity];
  const walk = (value: unknown) => {
    if (!Array.isArray(value) || value.length === 0) return;
    if (typeof value[0] === "number" && typeof value[1] === "number") {
      box[0] = Math.min(box[0], value[0]);
      box[1] = Math.min(box[1], value[1]);
      box[2] = Math.max(box[2], value[0]);
      box[3] = Math.max(box[3], value[1]);
      return;
    }
    for (const child of value) walk(child);
  };
  walk(geometry.coordinates);
  if (!Number.isFinite(box[0])) return null;
  return [
    [box[0], box[1]],
    [box[2], box[3]],
  ];
}

function plannedRouteData(plan: PlannedRoute | null): FeatureCollection {
  if (!plan) return EMPTY_COLLECTION;
  return {
    type: "FeatureCollection",
    features: [
      { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: plan.line } },
      ...plan.unreachable.map((point) => ({
        type: "Feature" as const,
        properties: {},
        geometry: { type: "Point" as const, coordinates: point },
      })),
    ],
  };
}

function showPlannedRoute(map: MapLibreMap, plan: PlannedRoute | null) {
  map.getSource<GeoJSONSource>("planned-route")?.setData(plannedRouteData(plan));
}

function fitPadding(container: HTMLElement): FitBoundsOptions["padding"] {
  if (container.clientWidth < 860) return { top: 150, bottom: 40, left: 24, right: 24 };
  return { top: 120, bottom: 80, left: 420, right: 400 };
}

function blockOpacity(base: number, block: string | null): number | ExpressionSpecification {
  if (block === null) return base;
  return ["case", ["==", ["get", "block"], block], base, base * 0.18];
}

function selectionFilter(fids: readonly number[]): ExpressionSpecification {
  if (fids.length === 0) return ["==", ["get", "fid"], -1];
  if (fids.length === 1) return ["==", ["get", "fid"], fids[0]];
  return ["any", ...fids.map((fid): ExpressionSpecification => ["==", ["get", "fid"], fid])];
}

function applySelection(map: MapLibreMap, fids: readonly number[]) {
  const filter = selectionFilter(fids);
  map.setFilter("selected-halo", filter);
  map.setFilter("selected-line", filter);
}

function applyBlock(map: MapLibreMap, block: string | null, revealing: boolean) {
  for (const [layer, property, base] of DIMMABLE) {
    const opacity = blockOpacity(base, block);
    map.setPaintProperty(layer, property, revealing ? withReveal(opacity) : opacity);
  }
}

function hasRoutes(data: FieldData): boolean {
  return data.items.some((item) => item.label === "route");
}

function revealLabel({ phase, rows, polygons, routes }: RevealProgress): string {
  if (phase === "scan") return "Scanning imagery…";
  if (phase === "rows") return `Detecting rows… ${rows.done}/${rows.total}`;
  if (phase === "polygons") return `Building polygons… ${polygons.done}/${polygons.total}`;
  if (phase === "routes") return `Tracing routes… ${routes.done}/${routes.total}`;
  return "Done";
}

function addFieldLayers(map: MapLibreMap, data: FieldData) {
  map.addSource("tile-frame", {
    type: "geojson",
    data: {
      type: "Feature",
      properties: {},
      geometry: { type: "Polygon", coordinates: [[...data.imageCorners, data.imageCorners[0]]] },
    },
  });
  map.addLayer({
    id: "tile-frame-fill",
    type: "fill",
    source: "tile-frame",
    paint: { "fill-color": MAP_COLORS.frame, "fill-opacity": 0.7 },
  });

  if (data.tiles) {
    const [[west, south], [east, north]] = data.bounds;
    map.addSource("orthophoto", {
      type: "raster",
      tiles: [data.tiles.url],
      tileSize: 256,
      bounds: [west, south, east, north],
      minzoom: data.tiles.minzoom,
      maxzoom: data.tiles.maxzoom,
    });
    map.addLayer({
      id: "orthophoto",
      type: "raster",
      source: "orthophoto",
      paint: { "raster-fade-duration": 0 },
    });
  }

  map.addLayer({
    id: "tile-frame-line",
    type: "line",
    source: "tile-frame",
    paint: { "line-color": MAP_COLORS.frameLine, "line-opacity": 0.45, "line-width": 1, "line-dasharray": [3, 3] },
  });

  map.addSource("field", { type: "geojson", data: data.mapFeatures, promoteId: "fid" });

  map.addLayer({
    id: "interrow-fill",
    type: "fill",
    source: "field",
    filter: byLabel("interrow_area"),
    paint: { "fill-color": MAP_COLORS.interrow, "fill-opacity": 0.42, "fill-opacity-transition": NO_TRANSITION },
  });
  map.addLayer({
    id: "interrow-line",
    type: "line",
    source: "field",
    filter: byLabel("interrow_area"),
    paint: {
      "line-color": MAP_COLORS.interrowLine,
      "line-width": 1,
      "line-opacity": 0.8,
      "line-opacity-transition": NO_TRANSITION,
    },
  });
  map.addLayer({
    id: "vineyard-fill",
    type: "fill",
    source: "field",
    filter: byLabel("vineyard"),
    paint: { "fill-color": MAP_COLORS.canopy, "fill-opacity": 0.4, "fill-opacity-transition": NO_TRANSITION },
  });
  map.addLayer({
    id: "vineyard-line",
    type: "line",
    source: "field",
    filter: byLabel("vineyard"),
    paint: {
      "line-color": MAP_COLORS.canopyLine,
      "line-width": 1,
      "line-opacity": 0.7,
      "line-opacity-transition": NO_TRANSITION,
    },
  });
  map.addLayer({
    id: "row-hit",
    type: "line",
    source: "field",
    filter: byLabel("row"),
    paint: { "line-color": MAP_COLORS.row, "line-width": 14, "line-opacity": 0 },
  });
  map.addLayer({
    id: "row-glow",
    type: "line",
    source: "field",
    filter: byLabel("row"),
    layout: { "line-cap": "round" },
    paint: {
      "line-color": MAP_COLORS.row,
      "line-width": 8,
      "line-blur": 6,
      "line-opacity": 0.35,
      "line-opacity-transition": NO_TRANSITION,
    },
  });
  map.addLayer({
    id: "row-line",
    type: "line",
    source: "field",
    filter: byLabel("row"),
    layout: { "line-cap": "round" },
    paint: {
      "line-color": MAP_COLORS.row,
      "line-width": 2.4,
      "line-opacity": 0.95,
      "line-opacity-transition": NO_TRANSITION,
    },
  });
  map.addLayer({
    id: "waste-fill",
    type: "fill",
    source: "field",
    filter: byLabel("waste"),
    paint: { "fill-color": MAP_COLORS.waste, "fill-opacity": 0.14, "fill-opacity-transition": NO_TRANSITION },
  });
  map.addLayer({
    id: "waste-glow",
    type: "line",
    source: "field",
    filter: byLabel("waste"),
    paint: {
      "line-color": MAP_COLORS.waste,
      "line-width": 7,
      "line-blur": 5,
      "line-opacity": 0.45,
      "line-opacity-transition": NO_TRANSITION,
    },
  });
  map.addLayer({
    id: "waste-line",
    type: "line",
    source: "field",
    filter: byLabel("waste"),
    paint: { "line-color": MAP_COLORS.waste, "line-width": 2, "line-opacity-transition": NO_TRANSITION },
  });
  map.addLayer({
    id: "route-hit",
    type: "line",
    source: "field",
    filter: byLabel("route"),
    paint: { "line-color": MAP_COLORS.route, "line-width": 14, "line-opacity": 0 },
  });
  map.addLayer({
    id: "route-glow",
    type: "line",
    source: "field",
    filter: byLabel("route"),
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": MAP_COLORS.route,
      "line-width": 11,
      "line-blur": 8,
      "line-opacity": 0.5,
      "line-opacity-transition": NO_TRANSITION,
    },
  });
  map.addLayer({
    id: "route-line",
    type: "line",
    source: "field",
    filter: byLabel("route"),
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": MAP_COLORS.route,
      "line-width": 3,
      "line-opacity": 0.95,
      "line-opacity-transition": NO_TRANSITION,
    },
  });
  map.addLayer({
    id: "route-flow",
    type: "line",
    source: "field",
    filter: byLabel("route"),
    layout: { "line-join": "round" },
    paint: {
      "line-color": MAP_COLORS.routeFlow,
      "line-width": 1.6,
      "line-dasharray": FLOW_DASH,
      "line-opacity": 0.85,
      "line-opacity-transition": NO_TRANSITION,
    },
  });

  map.addSource("planned-route", { type: "geojson", data: EMPTY_COLLECTION });
  const plannedLine: ExpressionSpecification = ["==", ["geometry-type"], "LineString"];
  map.addLayer({
    id: "planned-route-glow",
    type: "line",
    source: "planned-route",
    filter: plannedLine,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": MAP_COLORS.route, "line-width": 12, "line-blur": 8, "line-opacity": 0.55 },
  });
  map.addLayer({
    id: "planned-route-line",
    type: "line",
    source: "planned-route",
    filter: plannedLine,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": MAP_COLORS.route, "line-width": 3.2 },
  });
  map.addLayer({
    id: "planned-route-flow",
    type: "line",
    source: "planned-route",
    filter: plannedLine,
    layout: { "line-join": "round" },
    paint: { "line-color": MAP_COLORS.routeFlow, "line-width": 1.6, "line-dasharray": FLOW_DASH },
  });
  map.addLayer({
    id: "planned-route-miss",
    type: "circle",
    source: "planned-route",
    filter: ["==", ["geometry-type"], "Point"],
    paint: {
      "circle-radius": 7,
      "circle-color": "rgba(0, 0, 0, 0)",
      "circle-stroke-color": MAP_COLORS.waste,
      "circle-stroke-width": 2.5,
    },
  });

  map.addSource("cadastral", { type: "geojson", data: EMPTY_COLLECTION });
  map.addLayer({
    id: "cadastral-fill",
    type: "fill",
    source: "cadastral",
    paint: { "fill-color": MAP_COLORS.parcel, "fill-opacity": 0.18 },
  });
  map.addLayer({
    id: "cadastral-line",
    type: "line",
    source: "cadastral",
    paint: { "line-color": MAP_COLORS.parcelLine, "line-width": 2.5 },
  });

  const noSelection: ExpressionSpecification = ["==", ["get", "fid"], -1];
  map.addLayer({
    id: "selected-halo",
    type: "line",
    source: "field",
    filter: noSelection,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": MAP_COLORS.halo, "line-width": HALO_WIDTH, "line-opacity": HALO_OPACITY },
  });
  map.addLayer({
    id: "selected-line",
    type: "line",
    source: "field",
    filter: noSelection,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": [
        "match",
        ["get", "label"],
        "route",
        MAP_COLORS.route,
        "waste",
        MAP_COLORS.wasteSelected,
        "interrow_area",
        MAP_COLORS.interrowSelected,
        MAP_COLORS.row,
      ],
      "line-width": 3.5,
    },
  });
}

export type MapClick = {
  fids: number[];
  lngLat: LngLatPair;
  /** Command was held for this click. Cadastral lookup is gated on it. */
  metaKey: boolean;
};

export type MapInteraction = {
  /** Clicks toggle an allowed route target. Inter-rows and non-gap row axes are ignored. */
  pick: boolean;
  /** When pick is off, clicks drop the shared start/end point. */
  place: boolean;
};

interface MapViewProps {
  data: FieldData;
  highlightedIds: readonly number[];
  activeBlock: string | null;
  anchorLngLat: LngLatPair | null;
  interaction: MapInteraction;
  onMapClick: (click: MapClick) => void;
  /** Reveal progress for live counters; `null` once the reveal has finished or was skipped. */
  onRevealProgress?: (progress: RevealProgress | null) => void;
  plannedRoute?: PlannedRoute | null;
  cadastral?: CadastralFeature | null;
}

const HUD_LINGER_MS = 1400;

export function MapView({
  data,
  highlightedIds,
  activeBlock,
  anchorLngLat,
  interaction,
  onMapClick,
  onRevealProgress,
  plannedRoute = null,
  cadastral = null,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const readyRef = useRef(false);
  const onMapClickRef = useRef(onMapClick);
  const onRevealRef = useRef(onRevealProgress);
  const interactionRef = useRef(interaction);
  const stateRef = useRef({ highlightedIds, activeBlock, plannedRoute, cadastral });
  const lastBlockRef = useRef<string | null>(activeBlock);
  const revealRef = useRef<RevealHandle | null>(null);
  /** True while the real layers' opacity is multiplied by the reveal state. */
  const revealPaintRef = useRef(false);
  const ambientRef = useRef<AmbientMotion | null>(null);
  const replayRef = useRef<() => void>(() => {});
  const [zoom, setZoom] = useState<number | null>(null);
  const [reveal, setReveal] = useState<RevealProgress | null>(null);
  const [reducedMotion] = useState(prefersReducedMotion);

  useEffect(() => {
    onMapClickRef.current = onMapClick;
    onRevealRef.current = onRevealProgress;
    interactionRef.current = interaction;
    stateRef.current = { highlightedIds, activeBlock, plannedRoute, cadastral };
  });

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let map: MapLibreMap;
    try {
      map = new MapLibreMap({
        container,
        style: BASE_STYLE,
        bounds: data.bounds,
        fitBoundsOptions: { padding: fitPadding(container) },
        attributionControl: false,
        maxZoom: 24,
        dragRotate: false,
        pitchWithRotate: false,
        transformRequest: authorizeApiRequest,
      });
    } catch (error) {
      console.error(error);
      onRevealRef.current?.(null);
      return;
    }
    map.touchZoomRotate.disableRotation();
    mapRef.current = map;
    let hudTimer = 0;

    const setRevealPaint = (on: boolean) => {
      revealPaintRef.current = on;
      applyBlock(map, stateRef.current.activeBlock, on);
    };

    const endReveal = () => {
      revealRef.current = null;
      map.once("render", () => {
        if (readyRef.current && !revealRef.current) setRevealPaint(false);
      });
      map.triggerRepaint();
      onRevealRef.current?.(null);
      hudTimer = window.setTimeout(() => setReveal(null), HUD_LINGER_MS);
    };

    const startReveal = () => {
      revealRef.current?.cancel();
      window.clearTimeout(hudTimer);
      if (prefersReducedMotion()) {
        revealRef.current = null;
        setRevealPaint(false);
        setReveal(null);
        onRevealRef.current?.(null);
        return;
      }
      setRevealPaint(true);
      revealRef.current = playReveal(map, data, {
        beforeId: "selected-halo",
        onProgress: (progress) => {
          setReveal(progress);
          if (progress.phase !== "done") onRevealRef.current?.(progress);
        },
        onDone: endReveal,
      });
    };
    replayRef.current = () => {
      if (readyRef.current) startReveal();
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") revealRef.current?.skip();
    };
    window.addEventListener("keydown", onKeyDown);

    map.on("load", () => {
      addFieldLayers(map, data);
      readyRef.current = true;
      applySelection(map, stateRef.current.highlightedIds);
      lastBlockRef.current = stateRef.current.activeBlock;
      map.fitBounds(data.bounds, { padding: fitPadding(container), animate: false, maxZoom: 23 });
      setZoom(map.getZoom());
      showPlannedRoute(map, stateRef.current.plannedRoute);
      showCadastral(map, stateRef.current.cadastral);
      ambientRef.current = startAmbientMotion(map, {
        flow: (hasRoutes(data) || stateRef.current.plannedRoute !== null) && !prefersReducedMotion(),
      });
      ambientRef.current.setHalo(stateRef.current.highlightedIds.length > 0 && !prefersReducedMotion());
      startReveal();
    });

    map.on("zoom", () => setZoom(map.getZoom()));

    map.on("click", (event) => {
      if (!readyRef.current) return;
      revealRef.current?.skip();
      const rendered = map.queryRenderedFeatures(event.point, { layers: INTERACTIVE_LAYERS });
      const fids = orderClickedFids(
        rendered.map((hit) => ({
          fid: Number(hit.properties.fid),
          label: String(hit.properties.label ?? ""),
          layerId: hit.layer.id,
        })),
        interactionRef.current.pick,
      );
      onMapClickRef.current({
        fids,
        lngLat: [event.lngLat.lng, event.lngLat.lat],
        metaKey: event.originalEvent.metaKey,
      });
    });

    map.on("mousemove", (event) => {
      if (!readyRef.current) return;
      const { pick, place } = interactionRef.current;
      const over = map.queryRenderedFeatures(event.point, { layers: INTERACTIVE_LAYERS }).length > 0;
      const canvas = map.getCanvas();
      if (place && !pick) canvas.style.cursor = "crosshair";
      else if (over || !pick) canvas.style.cursor = "pointer";
      else if (place) canvas.style.cursor = "crosshair";
      else canvas.style.cursor = "";
    });

    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.clearTimeout(hudTimer);
      revealRef.current?.cancel();
      revealRef.current = null;
      ambientRef.current?.stop();
      ambientRef.current = null;
      replayRef.current = () => {};
      readyRef.current = false;
      revealPaintRef.current = false;
      mapRef.current = null;
      setReveal(null);
      map.remove();
    };
  }, [data]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    applySelection(map, highlightedIds);
    ambientRef.current?.setHalo(highlightedIds.length > 0 && !reducedMotion);
  }, [highlightedIds, reducedMotion]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    showPlannedRoute(map, plannedRoute);
    ambientRef.current?.setFlow((hasRoutes(data) || plannedRoute !== null) && !reducedMotion);
  }, [plannedRoute, data, reducedMotion]);

  useEffect(() => {
    const map = mapRef.current;
    const container = containerRef.current;
    if (!map || !container || !readyRef.current) return;
    showCadastral(map, cadastral);
    if (!cadastral) return;
    const bounds = geometryBounds(cadastral.geometry);
    if (bounds) map.fitBounds(bounds, { padding: fitPadding(container), maxZoom: 17, duration: reducedMotion ? 0 : 600 });
  }, [cadastral, reducedMotion]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !anchorLngLat) return;
    // The pin sits in the canvas container. Only the pin ignores hits; the container must keep
    // receiving pan and zoom.
    map.getCanvasContainer().style.pointerEvents = "";
    const element = document.createElement("div");
    element.className = "gbm-route-pin";
    element.setAttribute("role", "img");
    element.setAttribute("aria-label", "Route start and end");
    const marker = new Marker({ element, anchor: "center" }).setLngLat(anchorLngLat).addTo(map);
    marker.getElement().style.pointerEvents = "none";
    return () => {
      marker.remove();
    };
  }, [anchorLngLat]);

  useEffect(() => {
    const map = mapRef.current;
    const container = containerRef.current;
    if (!map || !container || !readyRef.current) return;
    applyBlock(map, activeBlock, revealPaintRef.current);
    if (lastBlockRef.current === activeBlock) return;
    lastBlockRef.current = activeBlock;
    const target = activeBlock === null ? data.bounds : blockBounds(data, activeBlock);
    if (target) map.fitBounds(target, { padding: fitPadding(container), maxZoom: 23, duration: 600 });
  }, [activeBlock, data]);

  const fitAll = () => {
    const map = mapRef.current;
    const container = containerRef.current;
    if (map && container) map.fitBounds(data.bounds, { padding: fitPadding(container), maxZoom: 23, duration: 500 });
  };

  const done = reveal?.phase === "done";

  return (
    <>
      <div ref={containerRef} className="gbm-map" />
      {reveal && (
        <div
          className={done ? "gbm-hud gbm-float is-done" : "gbm-hud gbm-float"}
          onClick={(e) => e.stopPropagation()}
        >
          <span className="gbm-sr-only" role="status">
            {reveal.phase === "done" ? "Annotations ready" : "Generating annotations"}
          </span>
          <div className="gbm-hud-head" aria-hidden="true">
            <span className="gbm-hud-dot" />
            <span className="gbm-hud-label">{revealLabel(reveal)}</span>
            <span className="gbm-hud-pct">{Math.round(reveal.fraction * 100)}%</span>
          </div>
          <div className="gbm-hud-bar" aria-hidden="true">
            <span style={{ transform: `scaleX(${reveal.fraction})` }} />
          </div>
          {!done && (
            <button type="button" className="gbm-hud-skip" onClick={() => revealRef.current?.skip()}>
              Skip <kbd>Esc</kbd>
            </button>
          )}
        </div>
      )}
      <div className="gbm-zoom gbm-float" onClick={(e) => e.stopPropagation()}>
        <button type="button" aria-label="Zoom in" onClick={() => mapRef.current?.zoomIn()}>
          +
        </button>
        <span className="gbm-zoom-value">{zoom === null ? "–" : zoom.toFixed(1)}</span>
        <button type="button" aria-label="Zoom out" onClick={() => mapRef.current?.zoomOut()}>
          −
        </button>
        <button type="button" aria-label="Fit tile" className="gbm-zoom-fit" onClick={fitAll}>
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
            <path
              d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
        {!reducedMotion && (
          <button
            type="button"
            aria-label="Replay animation"
            title="Replay animation"
            className="gbm-zoom-replay"
            onClick={() => replayRef.current()}
          >
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path
                d="M3 8a5 5 0 1 0 1.5-3.6M3 2.5v2.4h2.4"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        )}
      </div>
    </>
  );
}
