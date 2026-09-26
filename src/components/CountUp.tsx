import { useEffect, useRef, useState } from "react";
import { prefersReducedMotion } from "../lib/motion";

const easeOut = (t: number) => 1 - (1 - t) ** 3;

/** Eases from the value on screen to `target`. Starts at 0 on mount so numbers count up when they appear. */
function useCountUp(target: number, duration = 700): number {
  const [reduced] = useState(prefersReducedMotion);
  const [value, setValue] = useState(0);
  const shownRef = useRef(0);

  useEffect(() => {
    if (reduced) return;
    const from = shownRef.current;
    if (from === target) return;
    const started = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - started) / duration);
      shownRef.current = t === 1 ? target : from + (target - from) * easeOut(t);
      setValue(shownRef.current);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, duration, reduced]);

  return reduced ? target : value;
}

const whole = (value: number) => String(Math.round(value));

interface CountUpProps {
  value: number;
  format?: (value: number) => string;
}

/** Screen readers get the final value only, not every frame of the count. */
export function CountUp({ value, format = whole }: CountUpProps) {
  const shown = useCountUp(value);
  return (
    <span className="count-up">
      <span aria-hidden="true">{format(shown)}</span>
      <span className="sr-only">{format(value)}</span>
    </span>
  );
}
