import type { ReadinessResponse, VersionResponse } from "@/types/system";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function requestJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    cache: "no-store",
    headers: {
      Accept: "application/json",
    },
  });

  if (!response.ok && response.status !== 503) {
    throw new Error(`API request failed with HTTP ${response.status}`);
  }

  return (await response.json()) as T;
}

export function fetchReadiness(): Promise<ReadinessResponse> {
  return requestJson<ReadinessResponse>("/api/v1/ready");
}

export function fetchVersion(): Promise<VersionResponse> {
  return requestJson<VersionResponse>("/api/v1/version");
}
