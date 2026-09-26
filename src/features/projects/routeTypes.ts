/**
 * Walking routes from knowledge/knowledge/route.md. Targets are row gaps / possibly missing planting
 * (inspection locations) and detected waste; every route starts and ends at the supplied start point.
 */
export const ROUTE_TYPES = [
  {
    id: "full",
    name: "Full inspection walk",
    targets: "Row gaps, missing planting and waste",
  },
  {
    id: "inspection",
    name: "Row gap inspection",
    targets: "Row gaps ≥ 5 m and possibly missing planting",
  },
  {
    id: "waste",
    name: "Waste cleanup",
    targets: "Detected waste boxes",
  },
] as const;

export type RouteTypeId = (typeof ROUTE_TYPES)[number]["id"];

export const ROUTE_START_EPSG32635 = [629504.7, 5220250.75] as const;

export const ROUTE_RULES = [
  "Starts and returns to the start point within 5 m",
  "Walks only on inter-rows and authorised passages",
  "A target counts as visited within 2 m",
];
