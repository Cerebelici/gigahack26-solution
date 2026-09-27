import { isAxiosError } from "axios";

export function describeError(err: unknown, fallback: string): string {
  if (isAxiosError(err)) {
    if (err.code === "ECONNABORTED") return "The server took too long to respond.";
    if (!err.response) return "Could not reach the server.";
    const detail = (err.response.data as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && typeof detail[0]?.msg === "string") return detail[0].msg;
    return `${fallback} (HTTP ${err.response.status}).`;
  }
  return err instanceof Error ? err.message : fallback;
}
