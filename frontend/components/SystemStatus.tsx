"use client";

import { useEffect, useState } from "react";
import { fetchReadiness, fetchVersion } from "@/lib/api";
import type { ReadinessResponse, VersionResponse } from "@/types/system";

type RowState = "ok" | "pending" | "error";

type StatusRow = {
  label: string;
  message: string;
  state: RowState;
  value: string;
};

export function SystemStatus() {
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [version, setVersion] = useState<VersionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const [readyResult, versionResult] = await Promise.all([fetchReadiness(), fetchVersion()]);
        if (!active) {
          return;
        }
        setReadiness(readyResult);
        setVersion(versionResult);
        setError(null);
      } catch (caught) {
        if (!active) {
          return;
        }
        setError(caught instanceof Error ? caught.message : "Status konnte nicht geladen werden.");
      }
    }

    void load();
    const interval = window.setInterval(load, 15_000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  const rows: StatusRow[] = [
    {
      label: "API",
      message: error ?? "Read-only status endpoint",
      state: error ? "error" : readiness?.status === "ready" ? "ok" : "pending",
      value: readiness?.status ?? "loading",
    },
    {
      label: "Postgres",
      message: "Primary workflow system of record.",
      state: readiness?.dependencies.postgres ? "ok" : readiness ? "error" : "pending",
      value: readiness ? String(readiness.dependencies.postgres) : "loading",
    },
    {
      label: "MinIO",
      message: "Object storage health endpoint.",
      state: readiness?.dependencies.minio ? "ok" : readiness ? "error" : "pending",
      value: readiness ? String(readiness.dependencies.minio) : "loading",
    },
    {
      label: "Version",
      message: version?.phase ?? "Backend version metadata",
      state: version ? "ok" : error ? "error" : "pending",
      value: version?.version ?? "loading",
    },
  ];

  return (
    <section className="status-panel" aria-label="Systemstatus">
      <div className="status-header" aria-hidden="true">
        <span>Komponente</span>
        <span>Nachweis</span>
        <span>Status</span>
      </div>
      {rows.map((row) => (
        <div className="status-row" key={row.label}>
          <span className="status-label">{row.label}</span>
          <span className="status-message">{row.message}</span>
          <span className={`status-value state-${row.state}`}>{row.value}</span>
        </div>
      ))}
    </section>
  );
}
