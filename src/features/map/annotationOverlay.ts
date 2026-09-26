import type { FeatureCollection } from "geojson";
import type { Id } from "../../types/project";

const memory = new Map<string, FeatureCollection>();

function storageKey(projectId: Id): string {
  return `geobelic.tif-annotations.${projectId}`;
}

function isFeatureCollection(value: unknown): value is FeatureCollection {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as { type?: unknown }).type === "FeatureCollection" &&
    Array.isArray((value as { features?: unknown }).features)
  );
}

function readStorage(key: string): FeatureCollection | undefined {
  try {
    if (typeof sessionStorage === "undefined") return undefined;
    const raw = sessionStorage.getItem(key);
    if (!raw) return undefined;
    const parsed: unknown = JSON.parse(raw);
    return isFeatureCollection(parsed) ? parsed : undefined;
  } catch {
    return undefined;
  }
}

function writeStorage(key: string, features: FeatureCollection | null): void {
  try {
    if (typeof sessionStorage === "undefined") return;
    if (features && features.features.length > 0) sessionStorage.setItem(key, JSON.stringify(features));
    else sessionStorage.removeItem(key);
  } catch {
    // Quota or private-mode failures still leave the in-memory overlay for this page.
  }
}

/** Remember shapes from the latest `/process-tif` response. `null` clears the previous file. */
export function setAnnotationOverlay(projectId: Id, features: FeatureCollection | null): void {
  const key = storageKey(projectId);
  if (features && features.features.length > 0) memory.set(key, features);
  else memory.delete(key);
  writeStorage(key, features);
}

/** Overlay for this project, or undefined when the latest TIFF had no annotations. */
export function annotationOverlay(projectId: Id): FeatureCollection | undefined {
  const key = storageKey(projectId);
  if (memory.has(key)) return memory.get(key);
  const stored = readStorage(key);
  if (stored) memory.set(key, stored);
  return stored;
}
