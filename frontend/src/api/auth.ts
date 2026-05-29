import { unversionedClient } from './client';

export interface AuthStatus {
  bootstrapped: boolean;
}

export interface UserInfo {
  id: string;
  username: string;
  created_at: string;
}

export async function getAuthStatus(): Promise<AuthStatus> {
  const response = await unversionedClient.get<AuthStatus>('/auth/status');
  return response.data;
}

export async function register(username: string, password: string): Promise<UserInfo> {
  const response = await unversionedClient.post<UserInfo>('/auth/register', { username, password });
  return response.data;
}

export async function login(username: string, password: string): Promise<void> {
  await unversionedClient.post('/auth/login', { username, password });
}

export async function logout(): Promise<void> {
  await unversionedClient.post('/auth/logout');
}

export async function getMe(): Promise<UserInfo> {
  const response = await unversionedClient.get<UserInfo>('/auth/me');
  return response.data;
}
