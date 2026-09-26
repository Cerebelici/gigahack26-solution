import { ROUTE_RULES, ROUTE_TYPES, type RouteTypeId } from "./routeTypes";
import "../map/map.css";

type RoutePlannerProps = {
  routeType: RouteTypeId | null;
  targetPick: boolean;
  targetCount: number;
  anchor: [number, number] | null;
  onRouteType: (routeType: RouteTypeId) => void;
  onTargetPick: (pick: boolean) => void;
  onPlan: () => void;
};

type RoutePlacementProps = {
  routeType: RouteTypeId | null;
  targetPick: boolean;
  targetCount: number;
  anchor: [number, number] | null;
  onTargetPick: (pick: boolean) => void;
  onEdit: () => void;
};

function targetMeta(count: number): string {
  return `${count} ${count === 1 ? "target" : "targets"}`;
}

function TargetPickButton({ pressed, onClick }: { pressed: boolean; onClick: (pick: boolean) => void }) {
  return (
    <button
      type="button"
      className={pressed ? "gbm-route-pick is-active" : "gbm-route-pick"}
      aria-pressed={pressed}
      onClick={() => onClick(!pressed)}
    >
      {pressed ? "Selecting targets" : "Select targets"}
    </button>
  );
}

function AnchorLine({ anchor }: { anchor: [number, number] | null }) {
  if (!anchor) return null;
  return (
    <p className="gbm-route-point">
      Start and end {anchor[0].toFixed(2)}, {anchor[1].toFixed(2)}
    </p>
  );
}

export function RoutePlanner({
  routeType,
  targetPick,
  targetCount,
  anchor,
  onRouteType,
  onTargetPick,
  onPlan,
}: RoutePlannerProps) {
  return (
    <section className="gbm-route">
      <div className="gbm-section-head">
        <h4>Route planning</h4>
        <span>{targetMeta(targetCount)}</span>
      </div>

      <ul className="gbm-route-list" role="radiogroup" aria-label="Route type">
        {ROUTE_TYPES.map((type) => {
          const active = type.id === routeType;
          return (
            <li key={type.id}>
              <button
                type="button"
                role="radio"
                aria-checked={active}
                className={active ? "gbm-route-option is-active" : "gbm-route-option"}
                onClick={() => onRouteType(type.id)}
              >
                <span className="gbm-route-radio" aria-hidden="true" />
                <span className="gbm-route-name">{type.name}</span>
                <span className="gbm-route-targets">{type.targets}</span>
              </button>
            </li>
          );
        })}
      </ul>

      <TargetPickButton pressed={targetPick} onClick={onTargetPick} />
      {targetPick && (
        <p className="gbm-route-hint">
          Click an object to add or remove it. Inter-rows and row axes are not targets, except a disrupted row.
        </p>
      )}
      <AnchorLine anchor={anchor} />

      <button type="button" className="btn-primary gbm-route-submit" onClick={onPlan} disabled={routeType === null}>
        Plan route
      </button>

      <ul className="gbm-route-rules">
        {ROUTE_RULES.map((rule) => (
          <li key={rule}>{rule}</li>
        ))}
      </ul>
    </section>
  );
}

export function RoutePlacement({
  routeType,
  targetPick,
  targetCount,
  anchor,
  onTargetPick,
  onEdit,
}: RoutePlacementProps) {
  const name = ROUTE_TYPES.find((type) => type.id === routeType)?.name ?? "Route";
  return (
    <section className="gbm-route" aria-live="polite">
      <div className="gbm-section-head">
        <h4>{name}</h4>
        <span>{targetMeta(targetCount)}</span>
      </div>
      {anchor ? (
        <AnchorLine anchor={anchor} />
      ) : (
        <p className="gbm-route-hint">Click the map to place one point. That point is both the start and the end.</p>
      )}
      {targetPick && (
        <p className="gbm-route-hint">
          Clicks toggle targets. Inter-rows and row axes do nothing, except a disrupted row. Empty ground moves the
          start and end.
        </p>
      )}
      <TargetPickButton pressed={targetPick} onClick={onTargetPick} />
      <button type="button" className="gbm-text-btn gbm-route-edit" onClick={onEdit}>
        Route options
      </button>
    </section>
  );
}
