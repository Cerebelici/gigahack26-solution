import type { Feature, Geometry, Position } from "geojson";
import { measureArea, measureLength } from "./project";
import type { ProcessResult } from "./types";

const round = (value: number, digits: number) => Number(value.toFixed(digits));

function feature(geometry: Geometry, properties: Record<string, unknown>): Feature<Geometry, Record<string, unknown>> {
  return { type: "Feature", geometry, properties };
}

function row(
  vineyardId: string,
  rowId: string,
  from: Position,
  to: Position,
  rowStructure: "regular" | "disrupted" | "unassessable",
  missingVines = 0,
) {
  const geometry: Geometry = { type: "LineString", coordinates: [from, to] };
  const length = measureLength(geometry) ?? 0;
  return feature(geometry, {
    label: "row",
    vineyard_id: vineyardId,
    row_id: rowId,
    row_structure: rowStructure,
    length_m: round(length, 2),
    grapevine_count: Math.round(length / 1.2) - missingVines,
  });
}

function canopy(vineyardId: string, [cx, cy]: Position, radius = 0.8) {
  const ring: Position[] = Array.from({ length: 8 }, (_, i) => {
    const angle = (Math.PI / 4) * i + Math.PI / 8;
    return [round(cx + radius * Math.cos(angle), 3), round(cy + radius * Math.sin(angle), 3)];
  });
  ring.push(ring[0]);
  const geometry: Geometry = { type: "Polygon", coordinates: [ring] };
  const area = measureArea(geometry) ?? 0;
  return feature(geometry, {
    label: "vineyard",
    vineyard_id: vineyardId,
    area_m2: round(area, 3),
    area_ha: round(area / 10_000, 6),
  });
}

function box(minX: number, minY: number, maxX: number, maxY: number): Geometry {
  return {
    type: "Polygon",
    coordinates: [
      [
        [minX, minY],
        [maxX, minY],
        [maxX, maxY],
        [minX, maxY],
        [minX, minY],
      ],
    ],
  };
}

const lerp = (a: Position, b: Position, t: number): Position => [
  a[0] + (b[0] - a[0]) * t,
  a[1] + (b[1] - a[1]) * t,
];

const v02Start: Position = [629505, 5220231];
const v02End: Position = [629509, 5220263];

const interrow = box(629484.6, 5220233, 629485.9, 5220269);
const interrowArea = measureArea(interrow) ?? 0;

const waste = box(629519.6, 5220239.7, 629520.4, 5220240.3);

const route: Geometry = {
  type: "LineString",
  coordinates: [
    [629482, 5220228],
    [629500, 5220228],
    [629517, 5220228],
    [629520, 5220239.4],
  ],
};

export const sampleResult: ProcessResult = {
  tiles: null,
  boundsEpsg32635: [629479, 5220225, 629529, 5220275],
  features: {
    type: "FeatureCollection",
    features: [
      feature(interrow, {
        label: "interrow_area",
        vineyard_id: "V01",
        interrow_cover: "vegetation",
        area_m2: round(interrowArea, 3),
        area_ha: round(interrowArea / 10_000, 6),
      }),
      canopy("V01", [629484, 5220240]),
      canopy("V01", [629484, 5220252]),
      canopy("V01", [629484, 5220264], 0.7),
      canopy("V02", lerp(v02Start, v02End, 0.25)),
      canopy("V02", lerp(v02Start, v02End, 0.5), 0.75),
      canopy("V02", lerp(v02Start, v02End, 0.75)),
      row("V01", "V01-R01", [629484, 5220232], [629484, 5220270], "regular"),
      row("V01", "V01-R02", [629486.5, 5220232], [629486.5, 5220270], "regular"),
      row("V01", "V01-R03", [629489, 5220232], [629489, 5220270], "disrupted", 5),
      row("V01", "V01-R04", [629491.5, 5220233], [629491.5, 5220268], "regular"),
      row("V02", "V02-R01", v02Start, v02End, "regular"),
      row("V02", "V02-R02", [629508, 5220231], [629512.4, 5220266], "unassessable"),
      row("V02", "V02-R03", [629511, 5220231], [629514.6, 5220260], "disrupted", 6),
      feature(waste, { label: "waste", vineyard_id: "V02" }),
      feature(route, {
        label: "route",
        route_id: "RT-1",
        length_m: round(measureLength(route) ?? 0, 2),
      }),
    ],
  },
};