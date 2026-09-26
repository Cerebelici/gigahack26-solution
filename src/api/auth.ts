import { api } from "./client";
import type { AuthResponse, User } from "../types/project";

export async function signup(body: { email: string; password: string; name: string }): Promise<AuthResponse> {
  const res = await api.post<AuthResponse>("/auth/signup", body);
  return res.data;
}

export async function login(body: { email: string; password: string }): Promise<AuthResponse> {
  const res = await api.post<AuthResponse>("/auth/login", body);
  return res.data;
}

export async function fetchMe(): Promise<User> {
  const res = await api.get<User>("/auth/me");
  return res.data;
}
