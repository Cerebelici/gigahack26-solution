import type { FeatureCollection } from "geojson";
import type { RouteTypeId } from "../features/projects/routeTypes";
import type { ProcessResult } from "./process";

export type Id = string | number;

export type User = {
  id: Id;
  email: string;
  name: string;
};

export type AuthResponse = {
  token: string;
  user: User;
};

export type Raster = {
  id: Id;
  tileUrl: string; // template with {z}/{x}/{y}
  boundsEpsg32635: ProcessResult["boundsEpsg32635"];
  minzoom: number;
  maxzoom: number;
};

/** `features` are stored annotations in EPSG:32635; they may also carry `pixelRings`. */
export type Project = {
  id: Id;
  name: string;
  raster: Raster | null;
  features?: FeatureCollection | null;
};

export type RoutePlanResponse = {
  route: unknown | null;
  detail?: string;
};

/** One selected map feature. `fid` is the `buildFieldData` index; the other fields match that feature. */
export type RoutePlanTarget = {
  fid: number;
  label: string;
  vineyardId: string | null;
  rowId: string | null;
  /** Annotation id when the feature has one. */
  id: string | null;
};

/**
 * Body for `POST /projects/:id/routes`.
 * `start` and `end` are the same EPSG:32635 point: the walk leaves it and returns to it.
 * `targets` are existing map features (`fid` from `buildFieldData`), not a second object model.
 * A route type fills the selection with the objects it references; manual selection can include any feature.
 */
export type RoutePlanRequest = {
  routeType: RouteTypeId;
  start: [number, number];
  end: [number, number];
  targets: RoutePlanTarget[];
};
