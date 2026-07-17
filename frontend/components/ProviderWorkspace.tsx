"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  configureSimulationProvider,
  fetchCases,
  fetchExecution,
  fetchExecutions,
  fetchProviders,
  postProviderCommand,
} from "@/lib/api";
import type {
  AuthenticatedUser,
  CaseSummary,
  ExecutionDetail,
  ExecutionSummary,
  ProviderConfiguration,
  ProviderFeatureFlags,
} from "@/types/system";

const SCENARIOS = [
  "SUCCESS",
  "TEMPORARY_ERROR",
  "PERMANENT_ERROR",
  "TIMEOUT",
  "RATE_LIMIT",
  "DUPLICATE_RESPONSE",
  "DELAYED_RESPONSE",
  "AMBIGUOUS_STATUS",
  "ALREADY_PROCESSED",
  "INVALID_SIGNATURE",
  "INVALID_RESPONSE",
] as const;

type Props = { user: AuthenticatedUser };

export function ProviderWorkspace({ user }: Props) {
  const [providers, setProviders] = useState<ProviderConfiguration[]>([]);
  const [flags, setFlags] = useState<ProviderFeatureFlags | null>(null);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [executions, setExecutions] = useState<ExecutionSummary[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState("");
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [selectedExecution, setSelectedExecution] = useState<ExecutionDetail | null>(null);
  const [scenario, setScenario] = useState<(typeof SCENARIOS)[number]>("SUCCESS");
  const [technicalApprovalId, setTechnicalApprovalId] = useState("");
  const [reason, setReason] = useState("Kontrollierte lokale Simulation");
  const [message, setMessage] = useState("Providerstatus wird geladen …");
  const [busy, setBusy] = useState(false);

  const selectedProvider = useMemo(
    () => providers.find((provider) => provider.id === selectedProviderId) ?? providers[0],
    [providers, selectedProviderId],
  );
  const capability = selectedProvider?.capabilities[0];
  const selectedCase = useMemo(
    () => cases.find((item) => item.id === selectedCaseId) ?? cases[0],
    [cases, selectedCaseId],
  );
  const isAdmin = user.roles.includes("ADMIN");

  const load = useCallback(async () => {
    const [providerResult, executionResult, completedCases] = await Promise.all([
      fetchProviders(),
      fetchExecutions(),
      fetchCases("completed"),
    ]);
    setProviders(providerResult.items);
    setFlags(providerResult.feature_flags);
    setExecutions(executionResult.items);
    if (!selectedProviderId && providerResult.items[0]) {
      setSelectedProviderId(providerResult.items[0].id);
    }
    if (!selectedCaseId && completedCases.items[0]) setSelectedCaseId(completedCases.items[0].id);
    setCases(completedCases.items);
    setMessage("Providerzustand serverseitig geladen");
  }, [selectedCaseId, selectedProviderId]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load().catch((error: unknown) =>
        setMessage(error instanceof Error ? error.message : "Providerstatus fehlgeschlagen"),
      );
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function perform(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Provideraktion fehlgeschlagen");
    } finally {
      setBusy(false);
    }
  }

  async function configure() {
    await perform(async () => {
      const provider = await configureSimulationProvider();
      setSelectedProviderId(provider.id);
      setMessage("Simulationsprovider ohne produktive Außenwirkung konfiguriert");
    });
  }

  async function approveTechnically() {
    if (!selectedProvider || !capability || !selectedCase) return;
    await perform(async () => {
      const approval = await postProviderCommand<{ id: string }>(
        `/api/v1/providers/${selectedProvider.id}/technical-approvals`,
        { capability_id: capability.id, job_id: selectedCase.id, reason },
      );
      setTechnicalApprovalId(approval.id);
      setMessage("Technische Ausführungsfreigabe revisionsgebunden gespeichert");
    });
  }

  async function runDryRun() {
    if (!selectedProvider || !capability || !selectedCase) return;
    await perform(async () => {
      const result = await postProviderCommand<{
        replayed: boolean;
        execution: ExecutionDetail;
      }>(
        `/api/v1/providers/${selectedProvider.id}/dry-runs`,
        {
          capability_id: capability.id,
          job_id: selectedCase.id,
          operation: capability.operation,
          scenario,
          payload: { requested_by: user.email },
        },
        crypto.randomUUID(),
      );
      setSelectedExecution(result.execution);
      setMessage(
        result.replayed
          ? "Identischer Dry-Run wiederverwendet – keine Doppelwirkung"
          : "Dry-Run persistiert – Außenwirkung: nein",
      );
    });
  }

  async function queueSimulation() {
    if (!selectedProvider || !capability || !selectedCase || !technicalApprovalId) return;
    await perform(async () => {
      const result = await postProviderCommand<{
        replayed: boolean;
        execution: ExecutionDetail;
      }>(
        `/api/v1/providers/${selectedProvider.id}/executions`,
        {
          capability_id: capability.id,
          job_id: selectedCase.id,
          operation: capability.operation,
          scenario,
          technical_approval_id: technicalApprovalId,
          max_attempts: 3,
          retry_backoff_seconds: 1,
          payload: { requested_by: user.email },
        },
        crypto.randomUUID(),
      );
      setSelectedExecution(result.execution);
      setMessage(
        result.replayed
          ? "Identischer Auftrag wiederverwendet"
          : "Simulationsauftrag atomar mit Outbox gespeichert",
      );
    });
  }

  async function openExecution(orderId: string) {
    await perform(async () => {
      setSelectedExecution(await fetchExecution(orderId));
      setMessage("Ausführungs-, Outbox- und Versuchshistorie geladen");
    });
  }

  async function lifecycleAction(action: "resume" | "discard") {
    if (!selectedExecution) return;
    await perform(async () => {
      setSelectedExecution(
        await postProviderCommand<ExecutionDetail>(
          `/api/v1/executions/${selectedExecution.id}/${action}`,
          { reason },
        ),
      );
      setMessage(
        action === "resume"
          ? "Manuelle Wiederaufnahme auditiert"
          : "Endgültiges Verwerfen mit Begründung auditiert",
      );
    });
  }

  return (
    <section className="provider-workspace" aria-labelledby="provider-workspace-title">
      <div className="workspace-heading">
        <div>
          <p className="eyebrow">Phase 3 · sichere Integrationsgrenze</p>
          <h2 id="provider-workspace-title">Provider und Ausführungen</h2>
        </div>
        <p role="status">{message}</p>
      </div>

      <div className="provider-safety-grid" aria-label="Provider-Sicherheitsstatus">
        <span>Integration intern: {flags?.global_integration_enabled ? "aktiv" : "inaktiv"}</span>
        <span>Dry-Run: {flags?.dry_run_enabled ? "aktiv" : "inaktiv"}</span>
        <span>Produktiv: deaktiviert</span>
        <span>Callbacks: {flags?.callback_intake_enabled ? "aktiv" : "deaktiviert"}</span>
      </div>

      {providers.length === 0 ? (
        <div className="empty-provider">
          <p>Es ist noch kein lokaler Simulationsprovider konfiguriert.</p>
          {isAdmin ? (
            <button disabled={busy} onClick={() => void configure()} type="button">
              Simulationsprovider einrichten
            </button>
          ) : (
            <p>Nur Admins dürfen Providerkonfigurationen anlegen.</p>
          )}
        </div>
      ) : (
        <>
          <div className="field-grid provider-controls">
            <label>
              Provider
              <select
                onChange={(event) => setSelectedProviderId(event.target.value)}
                value={selectedProvider?.id ?? ""}
              >
                {providers.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Freigegebener Vorgang
              <select
                onChange={(event) => setSelectedCaseId(event.target.value)}
                value={selectedCase?.id ?? ""}
              >
                {cases.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title} · Rev. {item.version}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Simulationsszenario
              <select
                onChange={(event) => setScenario(event.target.value as typeof scenario)}
                value={scenario}
              >
                {SCENARIOS.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
            <label>
              Pflichtbegründung
              <input maxLength={2000} onChange={(event) => setReason(event.target.value)} value={reason} />
            </label>
          </div>

          <section className="provider-card">
            <div>
              <p className="eyebrow">{selectedProvider?.provider_type}</p>
              <h3>{selectedProvider?.name}</h3>
            </div>
            <p>
              Fähigkeit: {capability?.name ?? "keine"} · Operation: {capability?.operation ?? "–"}
            </p>
            <p>
              Secret-Referenz: {selectedProvider?.secret_reference?.name ?? "fehlt"} · ENV-Referenz:{" "}
              {selectedProvider?.secret_reference?.environment_variable ?? "fehlt"}
            </p>
            <p>Secretwert wird weder gespeichert noch angezeigt.</p>
            <div className="action-grid">
              <button disabled={busy || !selectedCase} onClick={() => void runDryRun()} type="button">
                Dry-Run starten
              </button>
              {isAdmin ? (
                <button
                  disabled={busy || !selectedCase || !reason.trim()}
                  onClick={() => void approveTechnically()}
                  type="button"
                >
                  Technisch freigeben
                </button>
              ) : null}
              <button
                disabled={busy || !technicalApprovalId}
                onClick={() => void queueSimulation()}
                type="button"
              >
                Simulationsauftrag erzeugen
              </button>
              <button disabled type="button">
                Produktiv ausführen – deaktiviert
              </button>
              <button disabled={busy} onClick={() => void load()} type="button">
                Status aktualisieren
              </button>
            </div>
          </section>
        </>
      )}

      <div className="execution-layout">
        <aside className="execution-list" aria-label="Ausführungsaufträge">
          <h3>Ausführungsaufträge</h3>
          {executions.map((execution) => (
            <button
              key={execution.id}
              onClick={() => void openExecution(execution.id)}
              type="button"
            >
              <strong>{execution.dry_run ? "Dry-Run" : execution.operation}</strong>
              <span>{execution.status} · Rev. {execution.job_revision}</span>
            </button>
          ))}
        </aside>

        {selectedExecution ? (
          <article className="execution-detail">
            <header>
              <div>
                <p className="eyebrow">Korrelation {selectedExecution.correlation_id}</p>
                <h3>{selectedExecution.status}</h3>
              </div>
              <span className="phase-badge">
                Außenwirkung: {selectedExecution.external_effect ? "ja" : "nein"}
              </span>
            </header>
            <section className="detail-block">
              <h4>Validierung und Payload</h4>
              <pre>{JSON.stringify(selectedExecution.prepared_payload, null, 2)}</pre>
              {selectedExecution.dry_run_result ? (
                <p>
                  Dry-Run gültig: {selectedExecution.dry_run_result.valid ? "ja" : "nein"} · Fehler:{" "}
                  {selectedExecution.dry_run_result.validation_errors.join(", ") || "keine"}
                </p>
              ) : null}
            </section>
            <section className="detail-block">
              <h4>Outbox und Versuche</h4>
              {selectedExecution.outbox.map((item) => (
                <p key={item.id}>
                  Outbox {item.sequence}: {item.status} · Versuche {item.attempts}
                  {item.last_error ? ` · ${item.last_error}` : ""}
                </p>
              ))}
              {selectedExecution.attempts.map((item) => (
                <p key={item.id}>
                  Versuch {item.attempt_number}: {item.status}
                  {item.error_classification ? ` · ${item.error_classification}` : ""}
                </p>
              ))}
              {selectedExecution.retry_plans.map((item) => (
                <p key={`${item.attempt_number}-${item.classification}`}>
                  Retry nach Versuch {item.attempt_number}: {item.classification} · Backoff{" "}
                  {item.backoff_seconds}s
                </p>
              ))}
            </section>
            <section className="detail-block">
              <h4>Providerantworten und Ergebnisartefakte</h4>
              {selectedExecution.responses.map((item, index) => (
                <p key={`${item.provider_status}-${index}`}>
                  {item.provider_status} → {item.normalized_status}
                </p>
              ))}
              {selectedExecution.artifacts.map((item) => (
                <p key={item.sha256}>{item.kind} · SHA-256 {item.sha256}</p>
              ))}
            </section>
            <section className="detail-block">
              <h4>Provider-Audit</h4>
              {selectedExecution.audit_events.map((item) => (
                <p key={item.id}>{item.event_type}</p>
              ))}
            </section>
            {isAdmin ? (
              <div className="action-grid">
                <button
                  disabled={busy || !["DEAD_LETTER", "AMBIGUOUS"].includes(selectedExecution.status)}
                  onClick={() => void lifecycleAction("resume")}
                  type="button"
                >
                  Fehler manuell wiederaufnehmen
                </button>
                <button
                  disabled={busy || selectedExecution.status === "SUCCEEDED" || !reason.trim()}
                  onClick={() => void lifecycleAction("discard")}
                  type="button"
                >
                  Endgültig verwerfen
                </button>
              </div>
            ) : null}
          </article>
        ) : (
          <p>Ausführung auswählen oder einen Dry-Run starten.</p>
        )}
      </div>
    </section>
  );
}
