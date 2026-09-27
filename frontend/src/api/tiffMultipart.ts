export type ParsedProcessTif = {
  /** Parsed JSON from the annotations part, or null when the response has no overlay. */
  annotations: unknown | null;
  /** Raw TIFF bytes when the response carried an image part. Null for a JSON tile response. */
  tiff: ArrayBuffer | null;
};

function mediaType(contentType: string): string {
  return contentType.split(";")[0]?.trim().toLowerCase() ?? "";
}

function isTiffType(type: string): boolean {
  return type === "image/tiff" || type === "image/x-tiff";
}

function asBytes(body: ArrayBuffer | Uint8Array): Uint8Array {
  return body instanceof Uint8Array ? body : new Uint8Array(body);
}

function copyBuffer(bytes: Uint8Array): ArrayBuffer {
  return new Uint8Array(bytes).buffer;
}

function latin1(bytes: Uint8Array): string {
  let text = "";
  for (let i = 0; i < bytes.length; i++) text += String.fromCharCode(bytes[i]);
  return text;
}

function indexOfBytes(haystack: Uint8Array, needle: Uint8Array, from = 0): number {
  if (needle.length === 0) return from;
  const last = haystack.length - needle.length;
  for (let i = Math.max(0, from); i <= last; i++) {
    let matched = true;
    for (let j = 0; j < needle.length; j++) {
      if (haystack[i + j] !== needle[j]) {
        matched = false;
        break;
      }
    }
    if (matched) return i;
  }
  return -1;
}

function findAllBytes(haystack: Uint8Array, needle: Uint8Array): number[] {
  const hits: number[] = [];
  let from = 0;
  while (from <= haystack.length - needle.length) {
    const at = indexOfBytes(haystack, needle, from);
    if (at < 0) break;
    hits.push(at);
    from = at + needle.length;
  }
  return hits;
}

function boundaryParam(contentType: string): string {
  const match = /boundary\s*=\s*(?:"([^"]+)"|([^;\s]+))/i.exec(contentType);
  const boundary = (match?.[1] ?? match?.[2])?.trim();
  if (!boundary) throw new Error("Multipart response is missing a boundary.");
  return boundary;
}

function headerParam(value: string, name: string): string | null {
  const match = new RegExp(`(?:^|;)\\s*${name}\\s*=\\s*(?:"([^"]*)"|([^;\\s]+))`, "i").exec(value);
  return match?.[1] ?? match?.[2] ?? null;
}

function parseHeaders(block: string): Map<string, string> {
  const headers = new Map<string, string>();
  for (const line of block.split(/\r?\n/)) {
    const split = line.indexOf(":");
    if (split < 0) continue;
    headers.set(line.slice(0, split).trim().toLowerCase(), line.slice(split + 1).trim());
  }
  return headers;
}

/** Drop the single MIME line break that frames a part, keeping bytes that belong to the body. */
function stripFraming(part: Uint8Array): Uint8Array {
  let start = 0;
  let end = part.length;
  if (part[start] === 13 && part[start + 1] === 10) start += 2;
  else if (part[start] === 10) start += 1;
  if (end - start >= 2 && part[end - 2] === 13 && part[end - 1] === 10) end -= 2;
  else if (end - start >= 1 && part[end - 1] === 10) end -= 1;
  return part.subarray(start, end);
}

function splitPart(part: Uint8Array): { headers: Map<string, string>; body: Uint8Array } | null {
  const framed = stripFraming(part);
  if (framed.length === 0) return null;
  const crlf = indexOfBytes(framed, new Uint8Array([13, 10, 13, 10]));
  if (crlf >= 0) {
    return { headers: parseHeaders(latin1(framed.subarray(0, crlf))), body: framed.subarray(crlf + 4) };
  }
  const lf = indexOfBytes(framed, new Uint8Array([10, 10]));
  if (lf >= 0) {
    return { headers: parseHeaders(latin1(framed.subarray(0, lf))), body: framed.subarray(lf + 2) };
  }
  throw new Error("Multipart part is missing a header block.");
}

function parseMultipart(contentType: string, body: ArrayBuffer): ParsedProcessTif {
  const boundary = boundaryParam(contentType);
  const bytes = asBytes(body);
  const marker = new TextEncoder().encode(`--${boundary}`);
  const hits = findAllBytes(bytes, marker);
  if (hits.length === 0) throw new Error("Multipart response did not contain the boundary.");

  let annotations: unknown | null = null;
  let tiff: ArrayBuffer | null = null;

  for (let i = 0; i < hits.length; i++) {
    const after = hits[i] + marker.length;
    if (bytes[after] === 45 && bytes[after + 1] === 45) break;
    const next = hits[i + 1] ?? bytes.length;
    const split = splitPart(bytes.subarray(after, next));
    if (!split) continue;

    const disposition = split.headers.get("content-disposition") ?? "";
    const name = headerParam(disposition, "name");
    const partType = mediaType(split.headers.get("content-type") ?? "");

    if (name === "annotations" || partType === "application/json") {
      if (annotations !== null) continue;
      try {
        annotations = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(split.body)) as unknown;
      } catch {
        throw new Error("Annotations part is not valid JSON.");
      }
      continue;
    }

    if (isTiffType(partType)) {
      if (!tiff) tiff = copyBuffer(split.body);
    }
  }

  if (!annotations) throw new Error("Multipart response is missing annotations.");
  if (!tiff || tiff.byteLength === 0) throw new Error("Multipart response is missing the TIFF.");
  return { annotations, tiff };
}

/**
 * Split a `/process-tif` body without decoding it as text.
 * `image/tiff` and a legacy JSON tile response carry no annotation overlay.
 */
export function parseProcessTifResponse(contentType: string, body: ArrayBuffer): ParsedProcessTif {
  const type = mediaType(contentType);
  if (isTiffType(type)) return { annotations: null, tiff: body };
  if (type === "application/json") return { annotations: null, tiff: null };
  if (type === "multipart/mixed") return parseMultipart(contentType, body);
  throw new Error(`Unexpected imagery response (${type || "unknown content type"}).`);
}
