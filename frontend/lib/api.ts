import type {
  AuthenticatedUser,
  LoginRequest,
  LoginResponse,
  ReadinessResponse,
  VersionResponse,
  CaseDetail,
  CaseSummary,
  ExecutionDetail,
  ExecutionSummary,
  ProviderConfiguration,
  ProviderListResponse,
  MediaAssetDetail,
  MediaAssetSummary,
  MediaCollection,
  MediaTaxonomy,
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
  return writeJsonWithHeaders<T>(path, body, csrfToken);
}

async function writeJsonWithHeaders<T>(
  path: string,
  body: unknown,
  csrfToken?: string,
  headers?: Record<string, string>,
  method = "POST",
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      ...headers,
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

export function postJson<T>(path: string, body: unknown = {}): Promise<T> {
  const csrf = readCsrfCookie();
  if (!csrf) {
    return Promise.reject(new Error("CSRF-Cookie fehlt"));
  }
  return writeJson<T>(path, body, csrf);
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

export function fetchCases(query = "open"): Promise<{
  items: CaseSummary[];
  page: number;
  page_size: number;
  total: number;
}> {
  return requestJson(`/api/v1/cases?queue=${encodeURIComponent(query)}&page_size=50`);
}

export function fetchCaseDetail(jobId: string): Promise<CaseDetail> {
  return requestJson<CaseDetail>(`/api/v1/cases/${jobId}`);
}

export function fetchProviders(): Promise<ProviderListResponse> {
  return requestJson<ProviderListResponse>("/api/v1/providers");
}

export function configureSimulationProvider(): Promise<ProviderConfiguration> {
  const csrf = readCsrfCookie();
  if (!csrf) return Promise.reject(new Error("CSRF-Cookie fehlt"));
  return writeJson<ProviderConfiguration>(
    "/api/v1/providers/simulation",
    {
      name: "Lokaler Simulationsprovider",
      secret_reference_name: "Lokale Callback-Signatur",
      secret_environment_variable: "MEDIAOS_SIMULATION_CALLBACK_SECRET",
      signature_profile_name: "HMAC-SHA256 lokal",
      capability_operation: "SIMULATE_CASE",
    },
    csrf,
  );
}

export function postProviderCommand<T>(
  path: string,
  body: unknown,
  idempotencyKey?: string,
): Promise<T> {
  const csrf = readCsrfCookie();
  if (!csrf) return Promise.reject(new Error("CSRF-Cookie fehlt"));
  return writeJsonWithHeaders<T>(
    path,
    body,
    csrf,
    idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
  );
}

export function fetchExecutions(): Promise<{ items: ExecutionSummary[] }> {
  return requestJson<{ items: ExecutionSummary[] }>("/api/v1/executions");
}

export function fetchExecution(orderId: string): Promise<ExecutionDetail> {
  return requestJson<ExecutionDetail>(`/api/v1/executions/${orderId}`);
}

export function fetchMediaAssets(
  query = "",
  page = 1,
): Promise<{
  items: MediaAssetSummary[];
  page: number;
  page_size: number;
  total: number;
}> {
  const params = new URLSearchParams({ query, page: String(page), page_size: "24" });
  return requestJson(`/api/v1/media-assets?${params.toString()}`);
}

export function fetchMediaAsset(assetId: string): Promise<MediaAssetDetail> {
  return requestJson<MediaAssetDetail>(`/api/v1/media-assets/${assetId}`);
}

export function fetchMediaTaxonomy(): Promise<MediaTaxonomy> {
  return requestJson<MediaTaxonomy>("/api/v1/media-taxonomy");
}

export function fetchMediaCollections(): Promise<{ items: MediaCollection[] }> {
  return requestJson<{ items: MediaCollection[] }>("/api/v1/media-collections");
}

export async function uploadMediaAsset(
  title: string,
  description: string,
  file: File,
): Promise<{ asset_id: string; duplicate_binary: boolean; quarantined: boolean }> {
  const csrf = readCsrfCookie();
  if (!csrf) throw new Error("CSRF-Cookie fehlt");
  const form = new FormData();
  form.append("title", title);
  form.append("description", description);
  form.append("upload", file);
  const response = await fetch(`${API_BASE_URL}/api/v1/media-assets`, {
    method: "POST",
    credentials: "include",
    headers: {
      "X-CSRF-Token": csrf,
      "Idempotency-Key": crypto.randomUUID(),
    },
    body: form,
  });
  if (!response.ok) {
    const payload = (await response.json()) as { message?: string };
    throw new Error(payload.message ?? `Upload fehlgeschlagen: HTTP ${response.status}`);
  }
  return (await response.json()) as {
    asset_id: string;
    duplicate_binary: boolean;
    quarantined: boolean;
  };
}

export async function uploadMediaVersion(
  assetId: string,
  revision: number,
  reason: string,
  file: File,
): Promise<void> {
  const csrf = readCsrfCookie();
  if (!csrf) throw new Error("CSRF-Cookie fehlt");
  const form = new FormData();
  form.append("expected_revision", String(revision));
  form.append("reason", reason);
  form.append("upload", file);
  const response = await fetch(`${API_BASE_URL}/api/v1/media-assets/${assetId}/versions`, {
    method: "POST",
    credentials: "include",
    headers: {
      "X-CSRF-Token": csrf,
      "Idempotency-Key": crypto.randomUUID(),
    },
    body: form,
  });
  if (!response.ok) throw new Error(`Neue Version fehlgeschlagen: HTTP ${response.status}`);
}

export function mediaCommand<T>(
  path: string,
  body: unknown = {},
  method: "POST" | "PUT" | "PATCH" | "DELETE" = "POST",
): Promise<T> {
  const csrf = readCsrfCookie();
  if (!csrf) return Promise.reject(new Error("CSRF-Cookie fehlt"));
  return writeJsonWithHeaders<T>(path, body, csrf, undefined, method);
}

export function mediaFileUrl(assetId: string, original = false, versionId?: string): string {
  const suffix = original ? "download" : "preview";
  const params = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
  return `${API_BASE_URL}/api/v1/media-assets/${assetId}/${suffix}${params}`;
}
