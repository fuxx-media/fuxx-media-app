import type {
  AuthenticatedUser,
  LoginRequest,
  LoginResponse,
  ReadinessResponse,
  VersionResponse,
} from "@/types/system";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function requestJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    cache: "no-store",
    credentials: "include",
    headers: {
      Accept: "application/json",
    },
  });

  if (!response.ok && response.status !== 503) {
    throw new Error(`API request failed with HTTP ${response.status}`);
  }

  return (await response.json()) as T;
}

async function writeJson<T>(path: string, body: unknown, csrfToken?: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = (await response.json()) as { message?: string };
    throw new Error(payload.message ?? `API request failed with HTTP ${response.status}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function fetchReadiness(): Promise<ReadinessResponse> {
  return requestJson<ReadinessResponse>("/api/v1/ready");
}

export function fetchVersion(): Promise<VersionResponse> {
  return requestJson<VersionResponse>("/api/v1/version");
}

export function login(body: LoginRequest): Promise<LoginResponse> {
  return writeJson<LoginResponse>("/api/v1/auth/login", body);
}

export function logout(csrfToken: string): Promise<void> {
  return writeJson<void>("/api/v1/auth/logout", {}, csrfToken);
}

export function fetchCurrentUser(): Promise<AuthenticatedUser> {
  return requestJson<AuthenticatedUser>("/api/v1/auth/me");
}

export function readCsrfCookie(): string | null {
  const pair = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith("mediaos_csrf="));
  return pair ? decodeURIComponent(pair.slice("mediaos_csrf=".length)) : null;
}
