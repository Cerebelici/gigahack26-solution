import { api } from "./client";
import type { Id, Project, Raster, RoutePlanRequest, RoutePlanResponse } from "../types/project";

// Large non-COG uploads are converted to a COG with overviews before the server responds.
export const RASTER_UPLOAD_TIMEOUT_MS = 15 * 60_000;

export async function listProjects(): Promise<Project[]> {
  const res = await api.get<Project[]>("/projects");
  return res.data;
}

export async function getProject(id: Id): Promise<Project> {
  const res = await api.get<Project>(`/projects/${id}`);
  return res.data;
}

export async function createProject(name: string): Promise<Project> {
  const res = await api.post<Project>("/projects", { name });
  return res.data;
}

export async function renameProject(id: Id, name: string): Promise<Project> {
  const res = await api.patch<Project>(`/projects/${id}`, { name });
  return res.data;
}

export async function deleteProject(id: Id): Promise<void> {
  await api.delete(`/projects/${id}`);
}

export async function uploadRaster(id: Id, files: File[], onProgress?: (fraction: number) => void): Promise<Raster> {
  const form = new FormData();
  for (const file of files) form.append("file", file);
  const res = await api.post<Raster>(`/projects/${id}/raster`, form, {
    timeout: RASTER_UPLOAD_TIMEOUT_MS,
    onUploadProgress: (event) => {
      if (onProgress && event.total) onProgress(event.loaded / event.total);
    },
  });
  return res.data;
}

/** Ready to call once the user has placed the start/end point. Does not run from the planner button. */
export async function planRoute(id: Id, request: RoutePlanRequest): Promise<RoutePlanResponse> {
  const res = await api.post<RoutePlanResponse>(`/projects/${id}/routes`, request);
  return res.data;
}
