import type { Feature, FeatureCollection, Geometry, Position } from "geojson";

export type AnnotationShape = "polygon" | "polyline" | "rectangle";

export type TiffAnnotationItem = {
  id?: string;
  label: string;
  shape: AnnotationShape;
  points: [number, number][];
  attributes?: Record<string, unknown>;
};

/** CVAT pixel annotations measured on the TIFF returned with them. */
export type TiffAnnotationDocument = {
  image: string;
  width: number;
  height: number;
  items: TiffAnnotationItem[];
};

/** Axis-aligned raster extent. West/north is the top-left of the image. */
export type MapExtent = {
  west: number;
  south: number;
  east: number;
  north: number;
};

const SHAPES = new Set<AnnotationShape>(["polygon", "polyline", "rectangle"]);

/**
 * CVAT pixel → map position on the raster extent.
 * Pixel (0, 0) is the northwest corner; pixel (width, height) is the southeast corner.
 * For this app the extent is the raster's EPSG:32635 bounds, and the map projects those metres to WGS84.
 */
export function pixelToMap(x: number, y: number, width: number, height: number, extent: MapExtent): [number, number] {
  if (!(width > 0) || !(height > 0)) throw new Error("Annotation image size must be positive.");
  return [
    extent.west + (x / width) * (extent.east - extent.west),
    extent.north - (y / height) * (extent.north - extent.south),
  ];
}

/** `[minX, minY, maxX, maxY]` from the raster, in the same order the map already stores. */
export function extentFromBounds([west, south, east, north]: [number, number, number, number]): MapExtent {
  return { west, south, east, north };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseItem(raw: unknown, index: number): TiffAnnotationItem {
  if (!isRecord(raw)) throw new Error(`Annotation ${index + 1} is not an object.`);
  if (typeof raw.label !== "string" || raw.label.trim() === "") {
    throw new Error(`Annotation ${index + 1} is missing a label.`);
  }
  if (typeof raw.shape !== "string" || !SHAPES.has(raw.shape as AnnotationShape)) {
    throw new Error(`Annotation ${index + 1} has an unsupported shape.`);
  }
  if (!Array.isArray(raw.points)) throw new Error(`Annotation ${index + 1} is missing points.`);

  const points = raw.points.map((point, pointIndex) => {
    if (
      !Array.isArray(point) ||
      point.length < 2 ||
      typeof point[0] !== "number" ||
      typeof point[1] !== "number" ||
      !Number.isFinite(point[0]) ||
      !Number.isFinite(point[1])
    ) {
      throw new Error(`Annotation ${index + 1} point ${pointIndex + 1} is invalid.`);
    }
    return [point[0], point[1]] as [number, number];
  });

  let id: string | undefined;
  if (raw.id !== undefined && raw.id !== null) {
    if (typeof raw.id !== "string" && typeof raw.id !== "number") {
      throw new Error(`Annotation ${index + 1} has an invalid id.`);
    }
    id = String(raw.id);
  }

  let attributes: Record<string, unknown> | undefined;
  if (raw.attributes !== undefined) {
    if (!isRecord(raw.attributes)) throw new Error(`Annotation ${index + 1} attributes must be an object.`);
    attributes = raw.attributes;
  }

  return { id, label: raw.label, shape: raw.shape as AnnotationShape, points, attributes };
}

export function parseAnnotationDocument(value: unknown): TiffAnnotationDocument {
  if (!isRecord(value)) throw new Error("Annotations JSON is not an object.");
  if (typeof value.image !== "string" || value.image === "") {
    throw new Error("Annotations JSON is missing the image name.");
  }
  if (typeof value.width !== "number" || typeof value.height !== "number" || !(value.width > 0) || !(value.height > 0)) {
    throw new Error("Annotations JSON needs a positive width and height.");
  }
  if (!Array.isArray(value.items)) throw new Error("Annotations JSON is missing items.");
  return {
    image: value.image,
    width: value.width,
    height: value.height,
    items: value.items.map(parseItem),
  };
}

function closeRing(ring: Position[]): Position[] {
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (!first || !last) return ring;
  if (first[0] === last[0] && first[1] === last[1]) return ring;
  return [...ring, [first[0], first[1]]];
}

function itemGeometry(item: TiffAnnotationItem, width: number, height: number, extent: MapExtent): Geometry {
  const coordinates = item.points.map(([x, y]) => pixelToMap(x, y, width, height, extent));
  if (item.shape === "polyline") {
    if (coordinates.length < 2) throw new Error(`"${item.label}" polyline needs at least two points.`);
    return { type: "LineString", coordinates };
  }
  if (coordinates.length < 3) throw new Error(`"${item.label}" ${item.shape} needs at least three points.`);
  return { type: "Polygon", coordinates: [closeRing(coordinates)] };
}

/** Pixel annotations as EPSG:32635 GeoJSON, ready for the existing map layers. */
export function annotationsToFeatures(doc: TiffAnnotationDocument, extent: MapExtent): FeatureCollection {
  const features: Feature[] = doc.items.map((item) => ({
    type: "Feature",
    ...(item.id !== undefined ? { id: item.id } : {}),
    geometry: itemGeometry(item, doc.width, doc.height, extent),
    properties: {
      ...item.attributes,
      label: item.label,
      ...(item.id !== undefined ? { id: item.id } : {}),
    },
  }));
  return { type: "FeatureCollection", features };
}
