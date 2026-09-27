import { lazy, Suspense, useState, type ComponentType } from "react";
import { Link } from "react-router-dom";
import { CountUp } from "../../components/CountUp";
import type { HeroSceneProps } from "./HeroScene";
import "./hero.css";

// three.js loads only with the hero. If the chunk fails, the CSS backdrop stays.
const HeroScene = lazy<ComponentType<HeroSceneProps>>(() =>
  import("./HeroScene").catch((error: unknown) => {
    console.error("Hero scene failed to load", error);
    return { default: () => null };
  }),
);

function Backdrop() {
  return (
    <div className="hero-backdrop">
      <span className="hero-blob" />
      <span className="hero-blob" />
      <span className="hero-blob" />
      <span className="hero-grid" />
      <span className="hero-scan" />
    </div>
  );
}

/** Full-viewport 3D survey behind the page. Decorative, so hidden from assistive technology. */
export function HeroStage() {
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <div className={ready && !failed ? "hero-stage is-ready" : "hero-stage"} aria-hidden="true">
      {(!ready || failed) && <Backdrop />}
      {!failed && (
        <Suspense fallback={null}>
          <HeroScene onReady={() => setReady(true)} onError={() => setFailed(true)} />
        </Suspense>
      )}
      <div className="hero-vignette" />
    </div>
  );
}

const STATS = [
  { value: 311, digits: 0, unit: "tiles", label: "orthophoto survey" },
  { value: 81.5, digits: 1, unit: "ha", label: "study area" },
  { value: 2.5, digits: 1, unit: "cm/px", label: "ground resolution" },
];

export function HeroCopy() {
  return (
    <section className="hero-copy" aria-labelledby="hero-title">
      <span className="hero-eyebrow">
        <span className="hero-live" aria-hidden="true" />
        AI vineyard intelligence
      </span>
      <h1 id="hero-title" className="hero-title">
        Every vine, <span>mapped from the sky.</span>
      </h1>
      <p className="hero-lede">
        Geobelic reads drone orthophotos of your vineyard, maps each row, canopy and inter-row, flags waste and row gaps,
        and plans the shortest inspection walk.
      </p>
      <div className="hero-actions">
        <Link to="/demo" className="btn-primary">
          Explore the sample map
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M3 8h9m0 0L8.5 4.5M12 8l-3.5 3.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </Link>
      </div>
      <dl className="hero-stats">
        {STATS.map((stat) => (
          <div key={stat.unit}>
            <dt>{stat.label}</dt>
            <dd>
              <CountUp value={stat.value} format={(n) => n.toFixed(stat.digits)} /> <small>{stat.unit}</small>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
