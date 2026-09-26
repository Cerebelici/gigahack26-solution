import axios from "axios";
import { clearSession, readToken } from "../auth/session";

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export const UNAUTHORIZED_EVENT = "geobelic:unauthorized";

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120_000,
});

// Wrong credentials also answer 401; those must surface as a form error, not a logout.
const CREDENTIAL_ENDPOINTS = ["/auth/login", "/auth/signup"];

api.interceptors.request.use((config) => {
  const token = readToken();
  if (token) config.headers.set("Authorization", `Bearer ${token}`);
  return config;
});

api.interceptors.response.use(undefined, (error) => {
  const url: string = error?.config?.url ?? "";
  if (error?.response?.status === 401 && !CREDENTIAL_ENDPOINTS.some((path) => url.endsWith(path))) {
    clearSession();
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
  return Promise.reject(error);
});

/** Absolute URL for a backend path; absolute URLs pass through unchanged. */
export function resolveApiUrl(url: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  return `${API_BASE_URL.replace(/\/$/, "")}/${url.replace(/^\//, "")}`;
}

/** MapLibre request hook: tiles served by our API get the session token. */
export function authorizeApiRequest(url: string): { url: string; headers?: Record<string, string> } {
  const token = readToken();
  if (!token || !url.startsWith(API_BASE_URL)) return { url };
  return { url, headers: { Authorization: `Bearer ${token}` } };
}
