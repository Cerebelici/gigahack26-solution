import type { LineString, Polygon, Position } from "geojson";
import { parseProcessTifResponse } from "../src/api/tiffMultipart";
import { annotationOverlay, setAnnotationOverlay } from "../src/features/map/annotationOverlay";
import { buildFieldData, toLngLat } from "../src/features/map/project";
import {
  annotationsToFeatures,
  parseAnnotationDocument,
  pixelToMap,
  type TiffAnnotationDocument,
} from "../src/features/map/tiffAnnotations";

function eq(actual: unknown, expected: unknown, message: string): void {
  const left = JSON.stringify(actual);
  const right = JSON.stringify(expected);
  if (left !== right) throw new Error(`${message}\nexpected ${right}\nactual   ${left}`);
}

function fail(message: string): never {
  throw new Error(message);
}

function concat(chunks: Uint8Array[]): Uint8Array {
  const size = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const out = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

function multipart(boundary: string, parts: Array<{ headers: string; body: Uint8Array }>): ArrayBuffer {
  const enc = new TextEncoder();
  const chunks: Uint8Array[] = [enc.encode("preamble\r\n")];
  for (const part of parts) {
    chunks.push(enc.encode(`--${boundary}\r\n${part.headers}\r\n\r\n`));
    chunks.push(part.body);
    chunks.push(enc.encode("\r\n"));
  }
  chunks.push(enc.encode(`--${boundary}--\r\n`));
  return concat(chunks).buffer;
}

function bytesOf(buffer: ArrayBuffer | null): number[] {
  if (!buffer) fail("expected TIFF bytes");
  return [...new Uint8Array(buffer)];
}

const boundary = "tiff-annotations-boundary";
const doc: TiffAnnotationDocument = {
  image: "siret3_r021_c012.tif",
  width: 4,
  height: 4,
  items: [
    {
      id: "v1",
      label: "vineyard",
      shape: "polygon",
      points: [
        [0, 0],
        [4, 0],
        [4, 4],
        [0, 4],
      ],
      attributes: { vineyard_id: "V01" },
    },
    {
      label: "interrow_area",
      shape: "polygon",
      points: [
        [0, 1],
        [1, 1],
        [1, 2],
      ],
      attributes: { interrow_cover: "bare_soil" },
    },
    {
      label: "row",
      shape: "polyline",
      points: [
        [0, 0],
        [4, 4],
      ],
      attributes: { row_id: "R1", row_structure: "regular" },
    },
    {
      label: "waste",
      shape: "rectangle",
      points: [
        [1, 1],
        [2, 1],
        [2, 2],
        [1, 2],
      ],
      attributes: { vineyard_id: "V02" },
    },
  ],
};

// 0xFF is not valid UTF-8 here; the TIFF also ends with CRLF so framing must not eat the body.
const tiff = Uint8Array.of(0x49, 0x49, 0x2a, 0x00, 0xff, 0x0d, 0x0a);
const body = multipart(boundary, [
  {
    headers:
      'Content-Disposition: form-data; name="annotations"\r\nContent-Type: application/json; charset=utf-8',
    body: new TextEncoder().encode(JSON.stringify(doc)),
  },
  {
    headers:
      'Content-Disposition: form-data; name="file"; filename="name=annotations.tif"\r\nContent-Type: image/tiff',
    body: tiff,
  },
]);

const parsed = parseProcessTifResponse(`multipart/mixed; boundary=${boundary}`, body);
const annotations = parseAnnotationDocument(parsed.annotations);
eq(annotations.image, doc.image, "annotation image name");
eq(annotations.items.map((item) => item.label), ["vineyard", "interrow_area", "row", "waste"], "labels");
eq(bytesOf(parsed.tiff), [...tiff], "TIFF bytes survive the multipart split");

const quoted = parseProcessTifResponse(`multipart/mixed; boundary="${boundary}"`, body);
eq(bytesOf(quoted.tiff), [...tiff], "quoted boundary");

const west = 10;
const south = 20;
const east = 50;
const north = 80;
const extent = { west, south, east, north };
eq(pixelToMap(0, 0, 4, 4, extent), [west, north], "pixel (0,0) is the northwest corner");
eq(pixelToMap(4, 4, 4, 4, extent), [east, south], "pixel (4,4) is the southeast corner");
eq(pixelToMap(2, 2, 4, 4, extent), [30, 50], "pixel center");

const features = annotationsToFeatures(annotations, extent);
const vineyard = features.features[0]?.geometry as Polygon;
const interrow = features.features[1]?.geometry as Polygon;
const row = features.features[2]?.geometry as LineString;
const waste = features.features[3]?.geometry as Polygon;

eq(
  vineyard.coordinates,
  [
    [
      [west, north],
      [east, north],
      [east, south],
      [west, south],
      [west, north],
    ],
  ],
  "polygon corners and closed ring",
);
eq(interrow.type, "Polygon", "inter-row is filled");
eq(row.type, "LineString", "row is a line");
eq(row.coordinates.length, 2, "polyline is not closed");
eq(row.coordinates, [[west, north], [east, south]], "polyline endpoints");
eq(waste.type, "Polygon", "rectangle is a polygon");
eq((waste.coordinates[0] ?? []).length, 5, "rectangle ring is closed");
eq(features.features[0]?.properties, { vineyard_id: "V01", label: "vineyard", id: "v1" }, "vineyard properties");
eq(features.features[2]?.properties, { row_id: "R1", row_structure: "regular", label: "row" }, "row properties");

const utmWest = 629000;
const utmSouth = 5220000;
const utmEast = 629004;
const utmNorth = 5220004;
const utmExtent = { west: utmWest, south: utmSouth, east: utmEast, north: utmNorth };
const placed = annotationsToFeatures(
  {
    image: "tile.tif",
    width: 4,
    height: 4,
    items: [
      {
        label: "vineyard",
        shape: "polygon",
        points: [
          [0, 0],
          [4, 0],
          [4, 4],
          [0, 4],
        ],
      },
    ],
  },
  utmExtent,
);
const field = buildFieldData({
  tiles: null,
  boundsEpsg32635: [utmWest, utmSouth, utmEast, utmNorth],
  features: placed,
});
const geometry = field.mapFeatures.features[0]?.geometry;
if (!geometry || geometry.type !== "Polygon") fail("expected the vineyard polygon on the map");
const ring = geometry.coordinates[0] ?? [];
const corner = (index: number): Position => ring[index] ?? fail(`missing corner ${index}`);
eq(corner(0), field.imageCorners[0], "pixel (0,0) maps to the displayed northwest corner");
eq(corner(2), field.imageCorners[2], "pixel (4,4) maps to the displayed southeast corner");
eq(toLngLat([utmWest, utmNorth]), field.imageCorners[0], "northwest corner is the top-left of the raster");

const tiffOnly = Uint8Array.of(0x4d, 0x4d, 0x00, 0x2a, 0xff);
for (const contentType of ["image/tiff", "image/x-tiff"]) {
  const only = parseProcessTifResponse(contentType, concat([tiffOnly]).buffer);
  if (only.annotations !== null) fail(`${contentType} should not carry annotations`);
  eq(bytesOf(only.tiff), [...tiffOnly], `${contentType} body`);
}

const legacy = parseProcessTifResponse(
  "application/json",
  concat([new TextEncoder().encode(JSON.stringify({ id: "raster", tileUrl: "/tiles" }))]).buffer,
);
if (legacy.annotations !== null || legacy.tiff !== null) fail("JSON tile response should not create an overlay");

setAnnotationOverlay("parcel", features);
const storedOverlay = annotationOverlay("parcel");
if (!storedOverlay || storedOverlay.features.length !== 4) fail("overlay was not stored");
setAnnotationOverlay("parcel", null);
if (annotationOverlay("parcel")) fail("previous annotation overlay stuck after a TIFF with no annotations");

let threw = false;
try {
  parseProcessTifResponse("text/plain", new ArrayBuffer(0));
} catch {
  threw = true;
}
if (!threw) fail("unexpected content type should fail");
