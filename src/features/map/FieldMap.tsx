import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { TopBar } from "../../components/TopBar";
import { prefersReducedMotion } from "../../lib/motion";
import type { Id, RoutePlanRequest } from "../../types/project";
import type { RouteTypeId } from "../projects/routeTypes";
import { RoutePlacement, RoutePlanner } from "../projects/RoutePlanner";
import {
  buildRoutePlanRequest,
  decideRouteClick,
  routeTargetFids,
} from "../projects/routeTargets";
import { MapView, type MapClick, type MapInteraction } from "./MapView";
import { fromLngLat, roundMetres, toLngLat } from "./project";
import { PENDING_REVEAL, revealShare, type RevealProgress } from "./revealAnimation";
import { BlocksCard, DetailCard, LegendChip } from "./SidePanels";
import type { FieldData } from "./types";
import "./map.css";

const NAV_COLLAPSED_KEY = "geobelic.mapNavCollapsed";

function readNavCollapsed() {
  try {
    return sessionStorage.getItem(NAV_COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

interface FieldMapProps {
  data: FieldData;
  /** Cards stacked above the blocks list in the left column. */
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
  const [navCollapsed, setNavCollapsed] = useState(readNavCollapsed);
  const [shownData, setShownData] = useState(data);
  const [routeType, setRouteType] = useState<RouteTypeId | null>(null);
  const [targetFids, setTargetFids] = useState<number[]>([]);
  const [anchor, setAnchor] = useState<[number, number] | null>(null);
  const [plannerOpen, setPlannerOpen] = useState(true);
  const [placing, setPlacing] = useState(false);
  const [targetPick, setTargetPick] = useState(false);
  const [reveal, setReveal] = useState<RevealProgress | null>(() => (prefersReducedMotion() ? null : PENDING_REVEAL));

  if (shownData !== data) {
    setShownData(data);
    setSelectedId(null);
    setActiveBlock(null);
    setRouteType(null);
    setTargetFids([]);
    setAnchor(null);
    setPlannerOpen(true);
    setPlacing(false);
    setTargetPick(false);
    setReveal(prefersReducedMotion() ? null : PENDING_REVEAL);
  }

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedId(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const routeHighlight =
    planRoute && (routeType !== null || targetPick || placing || targetFids.length > 0);

  const highlightedIds = useMemo(() => {
    if (routeHighlight) return targetFids;
    return selectedId === null ? [] : [selectedId];
  }, [routeHighlight, targetFids, selectedId]);

  const anchorLngLat = useMemo(() => (anchor ? toLngLat(anchor) : null), [anchor]);

  const routePlan = useMemo<RoutePlanRequest | null>(() => {
    if (!planRoute || !routeType || !anchor) return null;
    return buildRoutePlanRequest(routeType, data.items, targetFids, anchor);
  }, [planRoute, routeType, anchor, data.items, targetFids]);

  const interaction = useMemo<MapInteraction>(
    () => ({ pick: planRoute && targetPick, place: planRoute && placing }),
    [planRoute, targetPick, placing],
  );

  const chooseRouteType = useCallback(
    (next: RouteTypeId) => {
      setRouteType(next);
      setTargetFids(routeTargetFids(next, data.items));
    },
    [data.items],
  );

  const toggleTarget = useCallback((fid: number) => {
    setTargetFids((current) => (current.includes(fid) ? current.filter((id) => id !== fid) : [...current, fid]));
  }, []);

  const onTargetPick = useCallback((pick: boolean) => {
    setTargetPick(pick);
    if (pick) setSelectedId(null);
  }, []);

  const onMapClick = useCallback(
    ({ fids, lngLat }: MapClick) => {
      if (!planRoute) {
        setSelectedId(fids[0] ?? null);
        return;
      }
      const decision = decideRouteClick({ pick: targetPick, place: placing }, fids, data.items);
      if (decision.type === "ignore") return;
      if (decision.type === "toggle") {
        toggleTarget(decision.fid);
        return;
      }
      if (decision.type === "place") {
        const [x, y] = fromLngLat(lngLat);
        setAnchor([roundMetres(x), roundMetres(y)]);
        return;
      }
      setSelectedId(decision.fid);
    },
    [planRoute, targetPick, placing, data.items, toggleTarget],
  );

  const select = useCallback(
    (fid: number | null) => {
      if (fid !== null && planRoute && targetPick) {
        const decision = decideRouteClick({ pick: true, place: false }, [fid], data.items);
        if (decision.type === "toggle") toggleTarget(decision.fid);
        return;
      }
      setSelectedId(fid);
    },
    [planRoute, targetPick, data.items, toggleTarget],
  );

  const beginPlacement = useCallback(() => {
    setPlannerOpen(false);
    setPlacing(true);
    setTargetPick(false);
  }, []);

  const reopenPlanner = useCallback(() => {
    setPlannerOpen(true);
    setPlacing(false);
  }, []);

  const selected = selectedId === null ? null : (data.items[selectedId] ?? null);
  const rowShare = reveal ? revealShare(reveal.rows) : 1;
  const polygonShare = reveal ? revealShare(reveal.polygons) : 1;
  const hasItems = data.items.length > 0;
  const phase = !planRoute ? "off" : plannerOpen ? "choose" : anchor ? "placed" : "place";

  const setNav = useCallback((collapsed: boolean) => {
    setNavCollapsed(collapsed);
    try {
      sessionStorage.setItem(NAV_COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
      // Preference is optional; the toggle still works for this view.
    }
  }, []);

  return (
    <div className={["gbm-page", navCollapsed && "is-nav-collapsed", overlay && "has-banner"].filter(Boolean).join(" ")}>
      <MapView
        data={data}
        highlightedIds={highlightedIds}
        activeBlock={activeBlock}
        anchorLngLat={anchorLngLat}
        interaction={interaction}
        onMapClick={onMapClick}
        onRevealProgress={setReveal}
      />
      <div className="gbm-chrome">
        <div className="gbm-topbar-wrap" onClick={(event) => event.stopPropagation()}>
          <TopBar collapsed={navCollapsed} onToggle={() => setNav(!navCollapsed)} />
        </div>
        {overlay}
        <div className="gbm-left">
          {side}
          {planRoute && (
            <aside
              className="gbm-card gbm-project gbm-float"
              role={plannerOpen ? "dialog" : "status"}
              aria-label={plannerOpen ? "Route planning" : "Route start and end"}
              data-route-phase={phase}
              data-route-targets={targetFids.join(",")}
              data-route-project={projectId === undefined ? "" : String(projectId)}
              data-route-payload={routePlan ? JSON.stringify(routePlan) : ""}
            >
              {plannerOpen ? (
                <RoutePlanner
                  routeType={routeType}
                  targetPick={targetPick}
                  targetCount={targetFids.length}
                  anchor={anchor}
                  onRouteType={chooseRouteType}
                  onTargetPick={onTargetPick}
                  onPlan={beginPlacement}
                />
              ) : (
                <RoutePlacement
                  routeType={routeType}
                  targetPick={targetPick}
                  targetCount={targetFids.length}
                  anchor={anchor}
                  onTargetPick={onTargetPick}
                  onEdit={reopenPlanner}
                />
              )}
            </aside>
          )}
          {hasItems && (
            <BlocksCard
              blocks={data.blocks}
              items={data.items}
              activeBlock={activeBlock}
              onChange={setActiveBlock}
              rowShare={rowShare}
            />
          )}
        </div>
        {hasItems && (
          <DetailCard
            items={data.items}
            selected={selected}
            onSelect={select}
            rowShare={rowShare}
            polygonShare={polygonShare}
          />
        )}
        <LegendChip />
      </div>
    </div>
  );
}
