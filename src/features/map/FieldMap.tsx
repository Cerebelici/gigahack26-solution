import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Geometry } from "geojson";
import { describeError } from "../../api/errors";
import { lookupParcel, type ParcelLookup } from "../../api/geodata";
import { planRoute as requestRoute } from "../../api/projects";
import { TopBar } from "../../components/TopBar";
import { prefersReducedMotion } from "../../lib/motion";
import type { Id, RoutePlanRequest, RoutePlanResponse } from "../../types/project";
import { ROUTE_START_EPSG32635, type RouteTypeId } from "../projects/routeTypes";
import { RoutePlanner } from "../projects/RoutePlanner";
import {
  buildRoutePlanRequest,
  decideRouteClick,
  featuresInBlock,
  routeTargetFids,
} from "../projects/routeTargets";
import {
  MapView,
  type CadastralFeature,
  type MapClick,
  type MapInteraction,
  type MarkerGroup,
  type PlannedRoute,
} from "./MapView";
import { fromLngLat, mapGeometry, roundMetres, toLngLat } from "./project";
import { PENDING_REVEAL, revealShare, type RevealProgress } from "./revealAnimation";
import { BlocksCard, DetailCard, LegendChip, ParcelCard, type ParcelPhase } from "./SidePanels";
import type { FieldData } from "./types";
import "./map.css";

const NAV_COLLAPSED_KEY = "geobelic.mapNavCollapsed";
const LEFT_COLLAPSED_KEY = "geobelic.mapLeftCollapsed";

function readFlag(key: string) {
  try {
    return sessionStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function writeFlag(key: string, on: boolean) {
  try {
    sessionStorage.setItem(key, on ? "1" : "0");
  } catch {
    // Preference is optional; the toggle still works for this view.
  }
}

/** Feature geometry back in EPSG:32635 metres, for the route planner. */
function metreGeometries(data: FieldData): Map<number, Geometry> {
  const geometries = new Map<number, Geometry>();
  for (const feature of data.mapFeatures.features) {
    const fid = Number(feature.properties?.fid);
    if (feature.geometry && Number.isInteger(fid)) {
      geometries.set(fid, mapGeometry(feature.geometry, ([lng, lat]) => fromLngLat([lng, lat])));
    }
  }
  return geometries;
}

/** The challenge start point, when it lies on this imagery. */
function defaultStart(data: FieldData): [number, number] | null {
  const [lng, lat] = toLngLat([...ROUTE_START_EPSG32635]);
  const [[west, south], [east, north]] = data.bounds;
  return lng >= west && lng <= east && lat >= south && lat <= north ? [...ROUTE_START_EPSG32635] : null;
}

function routeError(err: unknown): string {
  const message = describeError(err, "Could not plan the route");
  if (message.includes("inside an obstacle")) return "The start point is on a vine row. Move it to open ground.";
  return message;
}

interface FieldMapProps {
  data: FieldData;
  /** Cards stacked above the route planner in the left column. */
  side?: ReactNode;
  /** Floating chrome such as banners. */
  overlay?: ReactNode;
  /** Show route planning. `projectId` is the id `planRoute` will use. */
  planRoute?: boolean;
  projectId?: Id;
}

export function FieldMap({ data, side, overlay, planRoute = false, projectId }: FieldMapProps) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [activeBlock, setActiveBlock] = useState<string | null>(null);
  const [navCollapsed, setNavCollapsed] = useState(() => readFlag(NAV_COLLAPSED_KEY));
  const [leftCollapsed, setLeftCollapsed] = useState(() => readFlag(LEFT_COLLAPSED_KEY));
  const [hiddenGroups, setHiddenGroups] = useState<ReadonlySet<MarkerGroup>>(() => new Set());

  const toggleGroup = useCallback((group: MarkerGroup) => {
    setHiddenGroups((current) => {
      const next = new Set(current);
      if (!next.delete(group)) next.add(group);
      return next;
    });
  }, []);
  const [shownData, setShownData] = useState(data);
  const [routeType, setRouteType] = useState<RouteTypeId | null>(null);
  const [targetFids, setTargetFids] = useState<number[]>([]);
  const [anchor, setAnchor] = useState<[number, number] | null>(null);
  const [placing, setPlacing] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [routeResult, setRouteResult] = useState<RoutePlanResponse | null>(null);
  const [routeFailure, setRouteFailure] = useState<string | null>(null);
  const [targetPick, setTargetPick] = useState(false);
  const [reveal, setReveal] = useState<RevealProgress | null>(() => (prefersReducedMotion() ? null : PENDING_REVEAL));
  const [parcelPhase, setParcelPhase] = useState<ParcelPhase | "idle">("idle");
  const [parcelLookup, setParcelLookup] = useState<ParcelLookup | null>(null);
  const [parcelError, setParcelError] = useState<string | null>(null);
  const parcelRequest = useRef(0);

  if (shownData !== data) {
    setShownData(data);
    setSelectedId(null);
    setActiveBlock(null);
    setRouteType(null);
    setTargetFids([]);
    setAnchor(null);
    setPlacing(false);
    setPlanning(false);
    setRouteResult(null);
    setRouteFailure(null);
    setTargetPick(false);
    setReveal(prefersReducedMotion() ? null : PENDING_REVEAL);
    parcelRequest.current += 1;
    setParcelPhase("idle");
    setParcelLookup(null);
    setParcelError(null);
  }

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setSelectedId(null);
      setPlacing(false);
      parcelRequest.current += 1;
      setParcelPhase("idle");
      setParcelLookup(null);
      setParcelError(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const routeHighlight =
    planRoute && (routeType !== null || targetPick || placing || targetFids.length > 0);

  const highlightedIds = useMemo(() => {
    // A calculated route sits under the target halo. The pulse widens those rows and hides the path.
    if (routeResult) return [];
    if (routeHighlight) return targetFids;
    return selectedId === null ? [] : [selectedId];
  }, [routeResult, routeHighlight, targetFids, selectedId]);

  const anchorLngLat = useMemo(() => (anchor ? toLngLat(anchor) : null), [anchor]);

  const geometries = useMemo(() => metreGeometries(data), [data]);
  const routeItems = useMemo(() => featuresInBlock(data.items, activeBlock), [data.items, activeBlock]);

  const routePlan = useMemo<RoutePlanRequest | null>(() => {
    if (!planRoute || activeBlock === null || !routeType || !anchor) return null;
    return buildRoutePlanRequest(routeType, routeItems, geometries, targetFids, anchor);
  }, [planRoute, activeBlock, routeType, anchor, routeItems, geometries, targetFids]);

  const plannedRoute = useMemo<PlannedRoute | null>(() => {
    if (!routeResult) return null;
    return {
      line: routeResult.route.coordinates.map((point) => toLngLat(point)),
      unreachable: routeResult.unreachable.map((point) => toLngLat(point)),
    };
  }, [routeResult]);

  const staleRoute = useCallback(() => {
    setRouteResult(null);
    setRouteFailure(null);
  }, []);

  const interaction = useMemo<MapInteraction>(
    () => ({ pick: planRoute && targetPick, place: planRoute && placing }),
    [planRoute, targetPick, placing],
  );

  const chooseRouteType = useCallback(
    (next: RouteTypeId) => {
      setRouteType(next);
      setTargetFids(routeTargetFids(next, routeItems));
      // Only the first choice fills in the start; switching type keeps a start the user cleared.
      if (routeType === null && !anchor) {
        const start = defaultStart(data);
        setAnchor(start);
        // Without a start the next map click must place one, so say so on the map right away.
        if (!start) {
          setPlacing(true);
          setTargetPick(false);
        }
      }
      staleRoute();
    },
    [routeType, anchor, data, routeItems, staleRoute],
  );

  const clearStart = useCallback(() => {
    setAnchor(null);
    setPlacing(false);
    staleRoute();
  }, [staleRoute]);

  const clearTargets = useCallback(() => {
    setTargetFids([]);
    setTargetPick(false);
    staleRoute();
  }, [staleRoute]);

  const resetRoute = useCallback(() => {
    setActiveBlock(null);
    setRouteType(null);
    setTargetFids([]);
    setAnchor(null);
    setPlacing(false);
    setTargetPick(false);
    staleRoute();
  }, [staleRoute]);

  const chooseBlock = useCallback(
    (block: string | null) => {
      setActiveBlock(block);
      if (!routeType) return;
      setTargetFids(routeTargetFids(routeType, featuresInBlock(data.items, block)));
      staleRoute();
    },
    [routeType, data.items, staleRoute],
  );

  const toggleTarget = useCallback(
    (fid: number) => {
      setTargetFids((current) => (current.includes(fid) ? current.filter((id) => id !== fid) : [...current, fid]));
      staleRoute();
    },
    [staleRoute],
  );

  const onTargetPick = useCallback((pick: boolean) => {
    setTargetPick(pick);
    if (pick) {
      setSelectedId(null);
      setPlacing(false);
    }
  }, []);

  const onPlace = useCallback((place: boolean) => {
    setPlacing(place);
    if (place) setTargetPick(false);
  }, []);

  const clearParcel = useCallback(() => {
    parcelRequest.current += 1;
    setParcelPhase("idle");
    setParcelLookup(null);
    setParcelError(null);
  }, []);

  const lookupCadastral = useCallback((lngLat: MapClick["lngLat"]) => {
    const request = ++parcelRequest.current;
    setParcelPhase("loading");
    setParcelLookup(null);
    setParcelError(null);
    lookupParcel(lngLat[1], lngLat[0])
      .then((body) => {
        if (parcelRequest.current !== request) return;
        setParcelLookup(body);
        setParcelPhase("ready");
      })
      .catch((err: unknown) => {
        if (parcelRequest.current !== request) return;
        setParcelLookup(null);
        setParcelError(describeError(err, "Could not look up this parcel"));
        setParcelPhase("error");
      });
  }, []);

  const onMapClick = useCallback(
    ({ fids, lngLat, metaKey }: MapClick) => {
      if (metaKey) lookupCadastral(lngLat);
      if (!planRoute) {
        setSelectedId(fids[0] ?? null);
        return;
      }
      const decision = decideRouteClick({ pick: targetPick, place: placing }, fids, targetPick ? routeItems : data.items);
      if (decision.type === "ignore") return;
      if (decision.type === "toggle") {
        toggleTarget(decision.fid);
        return;
      }
      if (decision.type === "place") {
        const [x, y] = fromLngLat(lngLat);
        setAnchor([roundMetres(x), roundMetres(y)]);
        setPlacing(false);
        staleRoute();
        return;
      }
      setSelectedId(decision.fid);
    },
    [planRoute, targetPick, placing, data.items, routeItems, toggleTarget, staleRoute, lookupCadastral],
  );

  const select = useCallback(
    (fid: number | null) => {
      if (fid !== null && planRoute && targetPick) {
        const decision = decideRouteClick({ pick: true, place: false }, [fid], routeItems);
        if (decision.type === "toggle") toggleTarget(decision.fid);
        return;
      }
      setSelectedId(fid);
    },
    [planRoute, targetPick, routeItems, toggleTarget],
  );

  const routeBlocker =
    activeBlock === null
      ? "Choose a vineyard."
      : projectId === undefined
        ? "Sign in and open a project to plan a route on it."
        : routeType === null
          ? "Choose a route type."
          : targetFids.length === 0
            ? "Add at least one target."
            : anchor === null
              ? "Place the start point on the map."
              : null;

  const planNow = useCallback(async () => {
    if (projectId === undefined || !routePlan) return;
    setPlanning(true);
    setRouteFailure(null);
    setTargetPick(false);
    setPlacing(false);
    try {
      setRouteResult(await requestRoute(projectId, routePlan));
    } catch (err) {
      setRouteResult(null);
      setRouteFailure(routeError(err));
    } finally {
      setPlanning(false);
    }
  }, [projectId, routePlan]);

  const selected = selectedId === null ? null : (data.items[selectedId] ?? null);
  const cadastral = useMemo<CadastralFeature | null>(() => {
    const geometry = parcelLookup?.parcel?.geometry;
    if (parcelPhase !== "ready" || !geometry) return null;
    return { type: "Feature", properties: {}, geometry };
  }, [parcelPhase, parcelLookup]);
  const rowShare = reveal ? revealShare(reveal.rows) : 1;
  const polygonShare = reveal ? revealShare(reveal.polygons) : 1;
  const hasItems = data.items.length > 0;
  const phase = !planRoute ? "off" : placing ? "place" : anchor ? "placed" : "choose";

  const setNav = useCallback((collapsed: boolean) => {
    setNavCollapsed(collapsed);
    writeFlag(NAV_COLLAPSED_KEY, collapsed);
  }, []);

  const setLeft = useCallback((collapsed: boolean) => {
    setLeftCollapsed(collapsed);
    writeFlag(LEFT_COLLAPSED_KEY, collapsed);
  }, []);

  return (
    <div
      className={["gbm-page", navCollapsed && "is-nav-collapsed", leftCollapsed && "is-left-collapsed", overlay && "has-banner"]
        .filter(Boolean)
        .join(" ")}
    >
      <MapView
        data={data}
        highlightedIds={highlightedIds}
        activeBlock={activeBlock}
        anchorLngLat={anchorLngLat}
        interaction={interaction}
        onMapClick={onMapClick}
        onRevealProgress={setReveal}
        plannedRoute={plannedRoute}
        cadastral={cadastral}
        hiddenGroups={hiddenGroups}
      />
      <div className="gbm-chrome">
        <div className="gbm-topbar-wrap" onClick={(event) => event.stopPropagation()}>
          <TopBar collapsed={navCollapsed} onToggle={() => setNav(!navCollapsed)} />
        </div>
        {overlay}
        {placing && (
          <div className="gbm-place-hint gbm-float" role="status">
            <span className="gbm-place-hint-dot" aria-hidden="true" />
            Click open ground to place the start and end point
            <button type="button" className="gbm-text-btn" onClick={() => setPlacing(false)}>
              Cancel <kbd>Esc</kbd>
            </button>
          </div>
        )}
        <button
          type="button"
          className="gbm-left-toggle gbm-float"
          aria-controls="gbm-left-panel"
          aria-expanded={!leftCollapsed}
          aria-label={leftCollapsed ? "Show side panel" : "Hide side panel"}
          title={leftCollapsed ? "Show side panel" : "Hide side panel"}
          onClick={(event) => {
            event.stopPropagation();
            setLeft(!leftCollapsed);
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M14.5 6 8.5 12l6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <div id="gbm-left-panel" className="gbm-left" inert={leftCollapsed ? true : undefined}>
          {side}
          {planRoute && (
            <aside
              className="gbm-card gbm-project gbm-float"
              role="region"
              aria-label="Route planning"
              data-route-phase={phase}
              data-route-targets={targetFids.join(",")}
              data-route-project={projectId === undefined ? "" : String(projectId)}
              data-route-payload={routePlan ? JSON.stringify(routePlan) : ""}
            >
              <RoutePlanner
                routeType={routeType}
                targetPick={targetPick}
                targetCount={targetFids.length}
                anchor={anchor}
                placing={placing}
                planning={planning}
                result={
                  routeResult && {
                    lengthM: routeResult.length_m,
                    visited: (routePlan?.targets.length ?? 0) - routeResult.unreachable.length,
                    unreachable: routeResult.unreachable.length,
                  }
                }
                error={routeFailure}
                blocker={routeBlocker}
                blocks={data.blocks}
                items={data.items}
                block={activeBlock}
                onBlock={chooseBlock}
                onRouteType={chooseRouteType}
                onTargetPick={onTargetPick}
                onPlace={onPlace}
                onPlan={planNow}
                onClearRoute={staleRoute}
                onClearStart={clearStart}
                onClearTargets={clearTargets}
                onReset={resetRoute}
              />
            </aside>
          )}
          {hasItems && !planRoute && (
            <BlocksCard
              blocks={data.blocks}
              items={data.items}
              activeBlock={activeBlock}
              onChange={chooseBlock}
              rowShare={rowShare}
            />
          )}
        </div>
        {(hasItems || parcelPhase !== "idle") && (
          <div className="gbm-right">
            {parcelPhase !== "idle" && (
              <ParcelCard phase={parcelPhase} lookup={parcelLookup} error={parcelError} onClear={clearParcel} />
            )}
            {hasItems && (
              <DetailCard
                items={data.items}
                selected={selected}
                onSelect={select}
                rowShare={rowShare}
                polygonShare={polygonShare}
              />
            )}
          </div>
        )}
        <LegendChip hidden={hiddenGroups} onToggle={toggleGroup} />
      </div>
    </div>
  );
}
