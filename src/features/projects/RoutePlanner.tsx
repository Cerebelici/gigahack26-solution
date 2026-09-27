import { ROUTE_RULES, ROUTE_TYPES, type RouteTypeId } from "./routeTypes";
import "../map/map.css";

export type RouteResult = {
  lengthM: number;
  visited: number;
  unreachable: number;
};

type RoutePlannerProps = {
  routeType: RouteTypeId | null;
  targetPick: boolean;
  targetCount: number;
  anchor: [number, number] | null;
  /** The next map click sets the start and end point. */
  placing: boolean;
  planning: boolean;
  result: RouteResult | null;
  error: string | null;
  /** Why the route cannot be planned yet, or null when it can. */
  blocker: string | null;
  /** Vineyard id the walk is limited to, or null for the whole field. */
  block: string | null;
  onRouteType: (routeType: RouteTypeId) => void;
  onTargetPick: (pick: boolean) => void;
  onPlace: (placing: boolean) => void;
  onPlan: () => void;
  onClearRoute: () => void;
  onClearStart: () => void;
  onClearTargets: () => void;
  /** Clears the route type, start point, targets, and planned route. */
  onReset: () => void;
};

function targetMeta(count: number): string {
  return `${count} ${count === 1 ? "target" : "targets"}`;
}

function StepHead({ step, title, done }: { step: number; title: string; done: boolean }) {
  return (
    <div className={done ? "gbm-route-step is-done" : "gbm-route-step"}>
      <span aria-hidden="true">{step}</span>
      {title}
    </div>
  );
}

export function RoutePlanner({
  routeType,
  targetPick,
  targetCount,
  anchor,
  placing,
  planning,
  result,
  error,
  blocker,
  block,
  onRouteType,
  onTargetPick,
  onPlace,
  onPlan,
  onClearRoute,
  onClearStart,
  onClearTargets,
  onReset,
}: RoutePlannerProps) {
  const touched = routeType !== null || anchor !== null || targetCount > 0 || result !== null;
  return (
    <section className="gbm-route">
      <div className="gbm-section-head">
        <h4>Route planning</h4>
        <span>{targetMeta(targetCount)}</span>
        {touched && (
          <button type="button" className="gbm-text-btn gbm-route-reset" onClick={onReset}>
            Reset
          </button>
        )}
      </div>
      {block && <p className="gbm-route-hint">This walk uses {block} only. Other blocks are left out.</p>}

      <StepHead step={1} title="Route type" done={routeType !== null} />
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
                {active && <span className="gbm-route-targets">{type.targets}</span>}
              </button>
            </li>
          );
        })}
      </ul>

      <StepHead step={2} title="Start and end point" done={anchor !== null} />
      {anchor && (
        <div className="gbm-route-row">
          <p className="gbm-route-point">
            {anchor[0].toFixed(2)}, {anchor[1].toFixed(2)}
          </p>
          <button type="button" className="gbm-text-btn" onClick={onClearStart} aria-label="Clear start point">
            Clear
          </button>
        </div>
      )}
      <button
        type="button"
        className={placing ? "gbm-route-pick is-active" : "gbm-route-pick"}
        aria-pressed={placing}
        onClick={() => onPlace(!placing)}
      >
        {placing ? "Click the map…" : anchor ? "Move start point" : "Place start point on map"}
      </button>
      {placing && (
        <p className="gbm-route-hint">
          Click open ground: a headland, a path or an inter-row. The walk leaves this point and returns to it.
        </p>
      )}

      <StepHead step={3} title="Targets" done={targetCount > 0} />
      <button
        type="button"
        className={targetPick ? "gbm-route-pick is-active" : "gbm-route-pick"}
        aria-pressed={targetPick}
        onClick={() => onTargetPick(!targetPick)}
      >
        {targetPick ? "Done selecting" : "Add or remove targets"}
      </button>
      {targetCount > 0 && (
        <button type="button" className="gbm-text-btn gbm-route-clear" onClick={onClearTargets}>
          Clear all {targetMeta(targetCount)}
        </button>
      )}
      {targetPick && (
        <p className="gbm-route-hint">
          Click an object to add or remove it. Inter-rows and row axes are not targets, except a disrupted row.
        </p>
      )}

      <details className="gbm-route-rules-box">
        <summary>Route rules</summary>
        <ul className="gbm-route-rules">
          {ROUTE_RULES.map((rule) => (
            <li key={rule}>{rule}</li>
          ))}
        </ul>
      </details>
      <div className="gbm-route-footer">
        <button
          type="button"
          className="btn-primary gbm-route-submit"
          onClick={onPlan}
          disabled={blocker !== null || planning}
          aria-describedby={blocker ? "route-blocker" : undefined}
        >
          {planning && <span className="spinner" aria-hidden="true" />}
          {planning ? "Planning route…" : result ? "Plan again" : "Plan route"}
        </button>
        {blocker && !planning && (
          <p id="route-blocker" className="gbm-route-hint">
            {blocker}
          </p>
        )}

        {error && (
          <div className="alert-error gbm-route-error" role="alert">
            {error}
          </div>
        )}
        {result && (
          <div className="gbm-route-result" role="status">
            <p>
              <strong>{(result.lengthM / 1000).toFixed(2)} km</strong> walk · {result.visited}{" "}
              {result.visited === 1 ? "stop" : "stops"}
            </p>
            {result.unreachable > 0 && (
              <p className="gbm-route-warning">
                {result.unreachable} {result.unreachable === 1 ? "target is" : "targets are"} out of reach (ringed on the
                map).
              </p>
            )}
            <button type="button" className="gbm-text-btn" onClick={onClearRoute}>
              Clear route
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
