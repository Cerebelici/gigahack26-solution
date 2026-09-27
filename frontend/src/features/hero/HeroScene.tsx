import { useEffect, useRef, useState } from "react";
import { prefersReducedMotion } from "../../lib/motion";
import {
  createVineyardScene,
  FIELD,
  ROW_COUNT,
  scannedAt,
  type SceneLayout,
  type SurveyPhase,
  type Telemetry,
} from "./vineyardScene";

const PHASE_LABELS: Record<SurveyPhase, string> = {
  scanning: "Scanning",
  turning: "Turning",
  complete: "Survey complete",
  routing: "Planning route",
  returning: "Returning to base",
};

const LAYER_W = 220;
const LAYER_H = 140;
const PAD = 10;
const INK = { soil: "#5b4630", row: "#c6e98a", canopy: "#4fd67a", waste: "#ffb547", route: "#a08cff", grid: "rgba(198,233,138,0.12)" };

function toLayer(x: number, z: number): [number, number] {
  const x0 = FIELD.x0 - FIELD.headland;
  const x1 = FIELD.x1 + FIELD.headland;
  const zFar = FIELD.zFar - FIELD.headland;
  const zNear = FIELD.zNear + FIELD.headland;
  return [PAD + ((x - x0) / (x1 - x0)) * (LAYER_W - PAD * 2), PAD + ((z - zFar) / (zNear - zFar)) * (LAYER_H - PAD * 2)];
}

function prepare(canvas: HTMLCanvasElement | null): CanvasRenderingContext2D | null {
  if (!canvas) return null;
  const ratio = Math.min(window.devicePixelRatio, 2);
  if (canvas.width !== LAYER_W * ratio) {
    canvas.width = LAYER_W * ratio;
    canvas.height = LAYER_H * ratio;
  }
  const context = canvas.getContext("2d");
  context?.setTransform(ratio, 0, 0, ratio, 0, 0);
  context?.clearRect(0, 0, LAYER_W, LAYER_H);
  return context;
}

function drawOrthophoto(canvas: HTMLCanvasElement | null, layout: SceneLayout) {
  const context = prepare(canvas);
  if (!context) return;
  const [ax, ay] = toLayer(FIELD.x0 - FIELD.headland, FIELD.zFar - FIELD.headland);
  const [bx, by] = toLayer(FIELD.x1 + FIELD.headland, FIELD.zNear + FIELD.headland);
  context.fillStyle = INK.soil;
  context.fillRect(ax, ay, bx - ax, by - ay);
  context.strokeStyle = "#3f8a3a";
  context.lineWidth = 1.6;
  for (const x of layout.rowXs) {
    const [px, top] = toLayer(x, FIELD.zFar);
    const [, bottom] = toLayer(x, FIELD.zNear);
    context.beginPath();
    context.moveTo(px, top);
    context.lineTo(px, bottom);
    context.stroke();
  }
}

function drawAnnotations(canvas: HTMLCanvasElement | null, layout: SceneLayout, t: Telemetry) {
  const context = prepare(canvas);
  if (!context) return;
  const { band, progress, intensity } = t.scan;
  context.globalAlpha = Math.max(0.15, intensity);
  context.strokeStyle = INK.canopy;
  context.lineWidth = 0.7;
  for (const [x, z] of layout.vines) {
    if (band < FIELD.bands && !scannedAt(x, z, band, progress)) continue;
    const [px, py] = toLayer(x, z);
    context.beginPath();
    context.arc(px, py, 0.9, 0, Math.PI * 2);
    context.stroke();
  }
  context.strokeStyle = INK.row;
  context.lineWidth = 0.8;
  for (const x of layout.rowXs) {
    context.beginPath();
    let drawing = false;
    for (let z = FIELD.zNear; z >= FIELD.zFar; z -= 4) {
      const on = band >= FIELD.bands || scannedAt(x, z, band, progress);
      const [px, py] = toLayer(x, z);
      if (on && !drawing) context.moveTo(px, py);
      else if (on) context.lineTo(px, py);
      drawing = on;
    }
    context.stroke();
  }
  context.strokeStyle = INK.waste;
  t.waste.forEach(({ x, z, found }) => {
    if (!found) return;
    const [px, py] = toLayer(x, z);
    context.strokeRect(px - 3, py - 3, 6, 6);
  });
  context.globalAlpha = 1;
}

function drawRoute(canvas: HTMLCanvasElement | null, layout: SceneLayout, t: Telemetry) {
  const context = prepare(canvas);
  if (!context || t.routeProgress <= 0) return;
  const target = t.routeProgress * t.routeLengthM;
  context.globalAlpha = t.phase === "returning" ? t.scan.intensity : 1;
  context.strokeStyle = INK.route;
  context.lineWidth = 1.6;
  context.shadowColor = INK.route;
  context.shadowBlur = 6;
  context.beginPath();
  let walked = 0;
  layout.route.forEach(([x, z], i) => {
    if (i > 0) walked += Math.hypot(x - layout.route[i - 1][0], z - layout.route[i - 1][1]);
    if (walked > target) return;
    const [px, py] = toLayer(x, z);
    if (i === 0) context.moveTo(px, py);
    else context.lineTo(px, py);
  });
  context.stroke();
  const [sx, sy] = toLayer(layout.route[0][0], layout.route[0][1]);
  context.shadowBlur = 0;
  context.fillStyle = "#f4ffe6";
  context.beginPath();
  context.arc(sx, sy, 3.2, 0, Math.PI * 2);
  context.fill();
  context.globalAlpha = 1;
}

const LAYERS = [
  { id: "ortho", label: "Orthophoto" },
  { id: "annotations", label: "Canopy · rows · waste" },
  { id: "route", label: "Inspection route" },
] as const;

const number = new Intl.NumberFormat("en");

export interface HeroSceneProps {
  onReady: () => void;
  onError: () => void;
}

/** WebGL survey scene with its game HUD. Decorative: the hero copy carries the message. */
export default function HeroScene({ onReady, onError }: HeroSceneProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const trackerRef = useRef<HTMLDivElement>(null);
  const layerRefs = useRef<Array<HTMLCanvasElement | null>>([]);
  const readyRef = useRef(onReady);
  const errorRef = useRef(onError);
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);

  useEffect(() => {
    readyRef.current = onReady;
    errorRef.current = onError;
  });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let layout: SceneLayout | null = null;
    let latest: Telemetry | null = null;
    const drawLayers = () => {
      if (!layout || !latest) return;
      drawAnnotations(layerRefs.current[1], layout, latest);
      drawRoute(layerRefs.current[2], layout, latest);
    };
    let scene: ReturnType<typeof createVineyardScene>;
    try {
      scene = createVineyardScene(canvas, {
        still: prefersReducedMotion(),
        onTelemetry: (next) => {
          latest = next;
          setTelemetry(next);
          drawLayers();
        },
        onDroneScreen: (x, y, visible) => {
          const tracker = trackerRef.current;
          if (!tracker) return;
          tracker.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0)`;
          tracker.style.opacity = visible ? "1" : "0";
        },
        onReady: () => readyRef.current(),
      });
    } catch (error) {
      console.error(error);
      errorRef.current();
      return;
    }
    layout = scene.layout;
    drawOrthophoto(layerRefs.current[0], layout);
    drawLayers();

    let visible = true;
    const update = () => scene.setRunning(visible && !document.hidden);
    const resize = new ResizeObserver(() => scene.resize());
    resize.observe(canvas);
    const intersection = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      update();
    });
    intersection.observe(canvas);
    const onPointer = (event: PointerEvent) =>
      scene.setPointer((event.clientX / window.innerWidth) * 2 - 1, (event.clientY / window.innerHeight) * 2 - 1);
    window.addEventListener("pointermove", onPointer);
    document.addEventListener("visibilitychange", update);
    update();

    return () => {
      resize.disconnect();
      intersection.disconnect();
      window.removeEventListener("pointermove", onPointer);
      document.removeEventListener("visibilitychange", update);
      scene.dispose();
    };
  }, []);

  const t = telemetry;
  const status = t ? (t.phase === "scanning" ? `Scanning band ${t.band + 1}/${t.bands}` : PHASE_LABELS[t.phase]) : "Linking…";
  const found = (markers: Telemetry["waste"]) => markers.filter((marker) => marker.found).length;

  return (
    <>
      <canvas ref={canvasRef} className="hero-canvas" />
      <div ref={trackerRef} className="hero-tracker">
        <span className="hero-tracker-ring" />
        <span className="hero-tracker-label">
          GB-SCOUT 07
          <small>{t ? `ALT ${t.altitude.toFixed(1)} m · ${Math.round(t.speedKmh)} km/h` : "—"}</small>
        </span>
      </div>

      <div className="hero-hud">
        <section className="hero-telemetry">
          <header>
            <span className="hero-live" />
            <span>Sireț3 survey</span>
            <b className={`hero-phase is-${t?.phase ?? "scanning"}`}>{status}</b>
          </header>
          <div className="hero-coverage">
            <span style={{ transform: `scaleX(${t?.coverage ?? 0})` }} />
          </div>
          <dl>
            <div>
              <dt>Coverage</dt>
              <dd>{t ? Math.round(t.coverage * 100) : 0}%</dd>
            </div>
            <div>
              <dt>Rows</dt>
              <dd>
                {t?.rowsDetected ?? 0}/{ROW_COUNT}
              </dd>
            </div>
            <div>
              <dt>Vines</dt>
              <dd>{number.format(t?.vinesAnalysed ?? 0)}</dd>
            </div>
            <div>
              <dt>Waste</dt>
              <dd className="is-waste">{t ? found(t.waste) : 0}</dd>
            </div>
            <div>
              <dt>Row gaps</dt>
              <dd className="is-gap">{t ? found(t.gaps) : 0}</dd>
            </div>
            <div>
              <dt>Route</dt>
              <dd className="is-route">{t && t.routeProgress > 0 ? `${((t.routeLengthM * t.routeProgress) / 1000).toFixed(2)} km` : "—"}</dd>
            </div>
          </dl>
          <footer>
            {t ? `${t.lat.toFixed(5)}° N · ${t.lon.toFixed(5)}° E` : "—"}
            <span>EPSG:32635</span>
          </footer>
        </section>

        <section className="hero-layers">
          {LAYERS.map((layer, index) => (
            <figure key={layer.id} className={`hero-layer is-${layer.id}`} style={{ zIndex: LAYERS.length - index }}>
              <canvas
                ref={(element) => {
                  layerRefs.current[index] = element;
                }}
                width={LAYER_W}
                height={LAYER_H}
              />
              <figcaption>
                <span>0{index + 1}</span> {layer.label}
              </figcaption>
            </figure>
          ))}
        </section>
      </div>
    </>
  );
}
