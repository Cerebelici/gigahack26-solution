import { useEffect, useRef, useState, type ReactNode } from "react";
import { flushSync } from "react-dom";
import { Routes, useLocation } from "react-router-dom";
import { prefersReducedMotion } from "../lib/motion";

const supportsViewTransitions = () => typeof document !== "undefined" && "startViewTransition" in document;

/**
 * `<Routes>` that renders the previous location until a View Transition has captured it.
 * Without the API, the keyed wrapper plays a CSS enter animation instead.
 */
export function AnimatedRoutes({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [captured, setCaptured] = useState(location);
  const capturedRef = useRef(location);
  const [transitions] = useState(() => supportsViewTransitions() && !prefersReducedMotion());
  const shown = transitions ? captured : location;

  useEffect(() => {
    if (!transitions || capturedRef.current === location) return;
    capturedRef.current = location;
    document.startViewTransition(() => flushSync(() => setCaptured(location)));
  }, [location, transitions]);

  return (
    <div key={shown.pathname} className={transitions ? undefined : "route-view"}>
      <Routes location={shown}>{children}</Routes>
    </div>
  );
}
