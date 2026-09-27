import { isAxiosError } from "axios";
import { api } from "./client";
import { RASTER_UPLOAD_TIMEOUT_MS } from "./projects";
import { parseProcessTifResponse, type ParsedProcessTif } from "./tiffMultipart";

function contentTypeOf(headers: unknown): string {
  if (!headers || typeof headers !== "object") return "";
  const value = (headers as Record<string, unknown>)["content-type"];
  if (Array.isArray(value)) return value.join(", ");
  return typeof value === "string" ? value : "";
}

/** Array-buffer error bodies are still JSON `{ detail }` from the API. */
function rehydrateAxiosBody(err: unknown): void {
  if (!isAxiosError(err)) return;
  const response = err.response;
  if (!response || !(response.data instanceof ArrayBuffer)) return;
  const text = new TextDecoder().decode(response.data).trim();
  if (!text) return;
  try {
    response.data = JSON.parse(text) as unknown;
  } catch {
    response.data = { detail: text.slice(0, 500) };
  }
}

/** POST the GeoTIFF to `/process-tif` and split annotations from the TIFF bytes when present. */
export async function processTif(file: File): Promise<ParsedProcessTif> {
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await api.post<ArrayBuffer>("/process-tif", form, {
      responseType: "arraybuffer",
      timeout: RASTER_UPLOAD_TIMEOUT_MS,
    });
    return parseProcessTifResponse(contentTypeOf(res.headers), res.data);
  } catch (err) {
    rehydrateAxiosBody(err);
    throw err;
  }
}
