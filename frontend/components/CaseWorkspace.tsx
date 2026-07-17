"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchCaseDetail, fetchCases, postJson } from "@/lib/api";
import type { AuthenticatedUser, CaseDetail, CasePriority, CaseSummary } from "@/types/system";

type Props = { user: AuthenticatedUser };

export function CaseWorkspace({ user }: Props) {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [selected, setSelected] = useState<CaseDetail | null>(null);
  const [queue, setQueue] = useState("open");
  const [category, setCategory] = useState("");
  const [priority, setPriority] = useState<CasePriority>("NORMAL");
  const [note, setNote] = useState("");
  const [evidence, setEvidence] = useState("");
  const [rejectionReason, setRejectionReason] = useState("Correction required");
  const [message, setMessage] = useState("Arbeitsliste wird geladen …");
  const [busy, setBusy] = useState(false);

  const loadCases = useCallback(async () => {
    const result = await fetchCases(queue);
    setCases(result.items);
    setMessage(`${result.total} Vorgänge geladen`);
  }, [queue]);

  const loadDetail = useCallback(async (jobId: string) => {
    const detail = await fetchCaseDetail(jobId);
    setSelected(detail);
    setCategory(detail.category ?? "");
    setPriority(detail.priority);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadCases().catch((error: unknown) =>
        setMessage(error instanceof Error ? error.message : "Arbeitsliste fehlgeschlagen"),
      );
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadCases]);

  async function mutate(path: string, body: unknown = {}) {
    setBusy(true);
    try {
      await postJson(path, body);
      if (selected) await loadDetail(selected.id);
      await loadCases();
      setMessage("Serverseitig gespeichert und auditiert");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Aktion fehlgeschlagen");
    } finally {
      setBusy(false);
    }
  }

  const pendingApproval = selected?.approvals.find(
    (approval) => approval.status === "PENDING" && !approval.invalidated_at,
  );
  const isCompleted = selected?.business_status === "COMPLETED";

  return (
    <section className="case-workspace" aria-labelledby="case-workspace-title">
      <div className="workspace-heading">
        <div>
          <p className="eyebrow">Phase 2 · interner Prozess</p>
          <h2 id="case-workspace-title">Vorgangsbearbeitung</h2>
        </div>
        <p role="status">{message}</p>
      </div>

      <div className="queue-tabs" aria-label="Arbeitslisten">
        {["open", "mine", "unassigned", "due", "approval", "rejected", "completed"].map((name) => (
          <button disabled={busy} key={name} onClick={() => setQueue(name)} type="button">
            {name}
          </button>
        ))}
      </div>

      <div className="case-layout">
        <aside className="case-list" aria-label="Vorgänge">
          {cases.map((item) => (
            <button
              className={selected?.id === item.id ? "case-row active" : "case-row"}
              key={item.id}
              onClick={() => void loadDetail(item.id)}
              type="button"
            >
              <strong>{item.title}</strong>
              <span>
                {item.business_status} · {item.priority} · Rev. {item.version}
              </span>
            </button>
          ))}
        </aside>

        {selected ? (
          <article className="case-detail">
            <header>
              <div>
                <p className="eyebrow">Revision {selected.version}</p>
                <h3>{selected.title}</h3>
              </div>
              <span className="phase-badge">{selected.business_status}</span>
            </header>

            <div className="action-grid">
              <button
                disabled={busy || isCompleted}
                onClick={() =>
                  void mutate(`/api/v1/cases/${selected.id}/claim`, {
                    expected_version: selected.version,
                  })
                }
                type="button"
              >
                Vorgang übernehmen
              </button>
              <button
                disabled={busy || isCompleted}
                onClick={() =>
                  void mutate(`/api/v1/cases/${selected.id}/claim/renew`, {
                    expected_version: selected.version,
                  })
                }
                type="button"
              >
                Claim verlängern
              </button>
            </div>

            <div className="field-grid">
              <label>
                Kategorie
                <input
                  maxLength={100}
                  onChange={(event) => setCategory(event.target.value)}
                  value={category}
                />
              </label>
              <label>
                Priorität
                <select
                  onChange={(event) => setPriority(event.target.value as CasePriority)}
                  value={priority}
                >
                  <option>LOW</option>
                  <option>NORMAL</option>
                  <option>HIGH</option>
                  <option>URGENT</option>
                </select>
              </label>
            </div>
            <div className="action-grid">
              <button
                disabled={busy || isCompleted}
                onClick={() =>
                  void mutate(`/api/v1/cases/${selected.id}/update`, {
                    expected_version: selected.version,
                    category,
                    priority,
                  })
                }
                type="button"
              >
                Klassifizierung speichern
              </button>
              <button
                disabled={busy || isCompleted}
                onClick={() =>
                  void mutate(`/api/v1/cases/${selected.id}/update`, {
                    expected_version: selected.version,
                    category,
                    priority,
                    due_at: new Date().toISOString(),
                  })
                }
                type="button"
              >
                Wiedervorlage jetzt
              </button>
              <button
                disabled={busy || isCompleted}
                onClick={() =>
                  void mutate(`/api/v1/cases/${selected.id}/update`, {
                    expected_version: selected.version,
                    category,
                    priority,
                    due_at: null,
                  })
                }
                type="button"
              >
                Wiedervorlage aktivieren
              </button>
            </div>

            <section className="detail-block">
              <h4>Dateien und Hashes</h4>
              {selected.attachments.map((file) => (
                <a
                  href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/files/${file.stored_file_id}/download`}
                  key={file.id}
                >
                  {file.filename} · {file.sha256}
                </a>
              ))}
            </section>

            <section className="detail-block">
              <h4>Prüfliste</h4>
              {selected.checklist.length === 0 ? (
                <button
                  disabled={busy || isCompleted}
                  onClick={() =>
                    void mutate(`/api/v1/cases/${selected.id}/checklist`, {
                      expected_version: selected.version,
                      titles: ["Identität geprüft", "Dokument geprüft"],
                    })
                  }
                  type="button"
                >
                  Prüfliste erzeugen
                </button>
              ) : (
                selected.checklist.map((item) => (
                  <button
                    disabled={busy || isCompleted}
                    key={item.id}
                    onClick={() =>
                      void mutate(`/api/v1/cases/${selected.id}/checklist/${item.id}`, {
                        expected_version: selected.version,
                        completed: !item.completed_at,
                      })
                    }
                    type="button"
                  >
                    {item.completed_at ? "✓" : "○"} {item.title}
                  </button>
                ))
              )}
            </section>

            <section className="detail-block">
              <h4>Interne Notiz</h4>
              <textarea
                maxLength={5000}
                onChange={(event) => setNote(event.target.value)}
                value={note}
              />
              <button
                disabled={busy || isCompleted || !note.trim()}
                onClick={() => {
                  void mutate(`/api/v1/cases/${selected.id}/notes`, {
                    expected_version: selected.version,
                    content: note,
                  });
                  setNote("");
                }}
                type="button"
              >
                Notiz revisionssicher speichern
              </button>
              {selected.notes.map((item) => (
                <p key={item.id}>
                  Rev. {item.revision}: {item.content}
                </p>
              ))}
            </section>

            <section className="detail-block">
              <h4>Evidenz</h4>
              <input
                maxLength={300}
                onChange={(event) => setEvidence(event.target.value)}
                placeholder="Herkunft"
                value={evidence}
              />
              <button
                disabled={busy || isCompleted || !evidence.trim()}
                onClick={() => {
                  void mutate(`/api/v1/cases/${selected.id}/evidence`, {
                    expected_version: selected.version,
                    source: evidence,
                    structured_data: { recorded_by: user.email },
                  });
                  setEvidence("");
                }}
                type="button"
              >
                Evidenz anlegen
              </button>
              {selected.evidence.map((item) => (
                <p key={item.id}>
                  Rev. {item.revision}: {item.source} · {item.verification_status}
                </p>
              ))}
            </section>

            <section className="detail-block">
              <h4>Freigabe</h4>
              <button
                disabled={busy || isCompleted}
                onClick={() =>
                  void mutate(`/api/v1/cases/${selected.id}/approval-requests`, {
                    expected_version: selected.version,
                  })
                }
                type="button"
              >
                Freigabe anfordern
              </button>
              {pendingApproval ? (
                <>
                  <button
                    disabled={busy || isCompleted}
                    onClick={() =>
                      void mutate(`/api/v1/cases/approvals/${pendingApproval.id}/claim`)
                    }
                    type="button"
                  >
                    Freigabe übernehmen
                  </button>
                  <button
                    disabled={busy || isCompleted}
                    onClick={() =>
                      void mutate(`/api/v1/cases/approvals/${pendingApproval.id}/resolve`, {
                        approved: true,
                      })
                    }
                    type="button"
                  >
                    Freigeben
                  </button>
                  <input
                    maxLength={2000}
                    onChange={(event) => setRejectionReason(event.target.value)}
                    value={rejectionReason}
                  />
                  <button
                    disabled={busy || isCompleted || !rejectionReason.trim()}
                    onClick={() =>
                      void mutate(`/api/v1/cases/approvals/${pendingApproval.id}/resolve`, {
                        approved: false,
                        reason: rejectionReason,
                      })
                    }
                    type="button"
                  >
                    Ablehnen
                  </button>
                </>
              ) : null}
              <button
                disabled={busy || isCompleted}
                onClick={() =>
                  void mutate(`/api/v1/cases/${selected.id}/close`, {
                    expected_version: selected.version,
                    reason: "Interne Prüfung abgeschlossen",
                  })
                }
                type="button"
              >
                Intern abschließen
              </button>
              {selected.approvals.map((approval) => (
                <p key={approval.id}>
                  Rev. {approval.revision} · {approval.status}
                  {approval.invalidated_at ? " · INVALIDIERT" : ""}
                  {approval.reason ? ` · ${approval.reason}` : ""}
                </p>
              ))}
            </section>

            <section className="detail-block">
              <h4>Revisionen und Audit</h4>
              {selected.revisions.map((item) => (
                <p key={item.id}>
                  Rev. {item.revision} · {item.change_type}
                </p>
              ))}
              {selected.audit_events.map((item) => (
                <p key={item.id}>{item.event_type}</p>
              ))}
            </section>
          </article>
        ) : (
          <p>Vorgang aus der Arbeitsliste auswählen.</p>
        )}
      </div>
    </section>
  );
}
