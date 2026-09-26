import type { Map as MapLibreMap } from "maplibre-gl";

export const HALO_OPACITY = 0.9;
export const HALO_WIDTH = 8;
export const FLOW_DASH = [0, 4, 3];

// MapLibre has no dash offset, so the flow steps through dash patterns that shift one gap along the line.
const FLOW_SEQUENCE = [
  [0, 4, 3],
  [0.5, 4, 2.5],
  [1, 4, 2],
  [1.5, 4, 1.5],
  [2, 4, 1],
  [2.5, 4, 0.5],
  [3, 4, 0],
  [0, 0.5, 3, 3.5],
  [0, 1, 3, 3],
  [0, 1.5, 3, 2.5],
  [0, 2, 3, 2],
  [0, 2.5, 3, 1.5],
  [0, 3, 3, 1],
  [0, 3.5, 3, 0.5],
];
const STEP_MS = 55;
const HALO_PERIOD_MS = 1600;

export interface AmbientMotion {
  setHalo(active: boolean): void;
  stop(): void;
}

/** Continuous route flow and selection pulse. Runs only while one of them has something to animate. */
export function startAmbientMotion(map: MapLibreMap, { flow }: { flow: boolean }): AmbientMotion {
  let halo = false;
  let raf = 0;
  let last = 0;
  let step = 0;
  let stopped = false;

  const tick = (now: number) => {
    raf = 0;
    if (stopped) return;
    if (now - last >= STEP_MS) {
      last = now;
      if (flow && map.getLayer("route-flow")) {
        step = (step + 1) % FLOW_SEQUENCE.length;
        map.setPaintProperty("route-flow", "line-dasharray", FLOW_SEQUENCE[step]);
      }
      if (halo && map.getLayer("selected-halo")) {
        const wave = 0.5 + 0.5 * Math.sin((now / HALO_PERIOD_MS) * Math.PI * 2);
        map.setPaintProperty("selected-halo", "line-opacity", 0.45 + (HALO_OPACITY - 0.45) * wave);
        map.setPaintProperty("selected-halo", "line-width", HALO_WIDTH - 1 + 5 * wave);
      }
    }
    schedule();
  };

  const schedule = () => {
    if (!raf && !stopped && (flow || halo)) raf = requestAnimationFrame(tick);
  };

  schedule();

  return {
    setHalo(active) {
      if (halo === active) return;
      halo = active;
      if (!active && map.getLayer("selected-halo")) {
        map.setPaintProperty("selected-halo", "line-opacity", HALO_OPACITY);
        map.setPaintProperty("selected-halo", "line-width", HALO_WIDTH);
      }
      schedule();
    },
    stop() {
      stopped = true;
      cancelAnimationFrame(raf);
    },
  };
}
