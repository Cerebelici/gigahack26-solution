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

export type Metres = [x: number, y: number];

/**
 * Body for `POST /projects/:id/routes`, all in EPSG:32635 metres.
 * The walk leaves `start` and returns to it, never entering an `obstacles` ring
 * or a `canopies` ring.
 */
export type RoutePlanRequest = {
  routeType: RouteTypeId;
  obstacles: Metres[][];
  canopies: Metres[][];
  start: Metres;
  targets: Metres[];
};

export type RoutePlanResponse = {
  route: { type: "LineString"; coordinates: Metres[] };
  length_m: number;
  /** Targets no walk reaches, as sent. */
  unreachable: Metres[];
};
