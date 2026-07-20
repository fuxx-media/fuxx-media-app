"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchMediaAsset,
  fetchMediaAssets,
  fetchMediaCollections,
  fetchMediaTaxonomy,
  mediaCommand,
  mediaFileUrl,
  uploadMediaAsset,
  uploadMediaVersion,
} from "@/lib/api";
import type {
  AuthenticatedUser,
  MediaAssetDetail,
  MediaAssetSummary,
  MediaCollection,
  MediaTaxonomy,
} from "@/types/system";

type Props = { user: AuthenticatedUser };

export function MediaWorkspace({ user }: Props) {
  const [items, setItems] = useState<MediaAssetSummary[]>([]);
  const [detail, setDetail] = useState<MediaAssetDetail | null>(null);
  const [taxonomy, setTaxonomy] = useState<MediaTaxonomy>({ categories: [], tags: [] });
  const [collections, setCollections] = useState<MediaCollection[]>([]);
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("Mediathek wird geladen …");
  const [busy, setBusy] = useState(false);
  const canWrite = user.roles.some((role) => role === "ADMIN" || role === "BACKOFFICE");
  const canReview = user.roles.some((role) => role === "ADMIN" || role === "REVIEWER");
  const canAdmin = user.roles.includes("ADMIN");

  const reload = useCallback(async () => {
    const [assets, taxonomyResult, collectionResult] = await Promise.all([
      fetchMediaAssets(query),
      fetchMediaTaxonomy(),
      fetchMediaCollections(),
    ]);
    setItems(assets.items);
    setTaxonomy(taxonomyResult);
    setCollections(collectionResult.items);
    if (detail) setDetail(await fetchMediaAsset(detail.id));
    setMessage(`${assets.total} Medienobjekte`);
  }, [detail, query]);

  useEffect(() => {
    void Promise.all([fetchMediaAssets(), fetchMediaTaxonomy(), fetchMediaCollections()])
      .then(([assets, taxonomyResult, collectionResult]) => {
        setItems(assets.items);
        setTaxonomy(taxonomyResult);
        setCollections(collectionResult.items);
        setMessage(`${assets.total} Medienobjekte`);
      })
      .catch((error) =>
        setMessage(error instanceof Error ? error.message : "Laden fehlgeschlagen"),
      );
  }, []);

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    try {
      await action();
      await reload();
      setMessage(success);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Aktion fehlgeschlagen");
    } finally {
      setBusy(false);
    }
  }

  async function selectAsset(id: string) {
    setBusy(true);
    try {
      setDetail(await fetchMediaAsset(id));
      setMessage("Medienobjekt geladen");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Detailansicht fehlgeschlagen");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="media-workspace" aria-labelledby="media-title">
      <header className="workspace-heading">
        <div>
          <p className="eyebrow">Hauptblock 6</p>
          <h2 id="media-title">Versionierte Mediathek</h2>
        </div>
        <p>Privat · mandantengetrennt · keine Veröffentlichung</p>
      </header>
      <p className="auth-message" role="status">
        {message}
      </p>

      <div className="media-toolbar">
        <label>
          Suche
          <input value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
        <button disabled={busy} onClick={() => void reload()} type="button">
          Suchen
        </button>
      </div>

      {canWrite ? <UploadPanel busy={busy} run={run} /> : null}

      <div className="media-layout">
        <div className="media-list" aria-label="Medienliste">
          {items.map((item) => (
            <button
              className={detail?.id === item.id ? "media-row active" : "media-row"}
              disabled={busy}
              key={item.id}
              onClick={() => void selectAsset(item.id)}
              type="button"
            >
              <strong>{item.title}</strong>
              <span>
                {item.media_type} · {item.status}
              </span>
              <span>Version {item.current_version_number}</span>
            </button>
          ))}
          {items.length === 0 ? <p>Keine Medien gefunden.</p> : null}
        </div>
        {detail ? (
          <MediaDetail
            busy={busy}
            canAdmin={canAdmin}
            canReview={canReview}
            canWrite={canWrite}
            collections={collections}
            detail={detail}
            items={items}
            key={`${detail.id}:${detail.revision}`}
            run={run}
            taxonomy={taxonomy}
          />
        ) : (
          <div className="media-detail">
            <p>Medienobjekt auswählen.</p>
          </div>
        )}
      </div>
    </section>
  );
}

function UploadPanel({ busy, run }: { busy: boolean; run: RunAction }) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    void run(async () => {
      const result = await uploadMediaAsset(title, description, file);
      setTitle("");
      setDescription("");
      setFile(null);
      return result;
    }, "Upload gespeichert und technische Prüfung eingeplant");
  }

  return (
    <form className="media-upload" onSubmit={submit}>
      <label>
        Titel
        <input required value={title} onChange={(event) => setTitle(event.target.value)} />
      </label>
      <label>
        Beschreibung
        <input value={description} onChange={(event) => setDescription(event.target.value)} />
      </label>
      <label>
        Datei
        <input
          accept=".jpg,.jpeg,.png,.webp,.pdf,.mp3,.wav,.mp4"
          required
          type="file"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
      </label>
      <button disabled={busy || !file} type="submit">
        Privat hochladen
      </button>
    </form>
  );
}

type RunAction = (action: () => Promise<unknown>, success: string) => Promise<void>;

function MediaDetail({
  busy,
  canAdmin,
  canReview,
  canWrite,
  collections,
  detail,
  items,
  run,
  taxonomy,
}: {
  busy: boolean;
  canAdmin: boolean;
  canReview: boolean;
  canWrite: boolean;
  collections: MediaCollection[];
  detail: MediaAssetDetail;
  items: MediaAssetSummary[];
  run: RunAction;
  taxonomy: MediaTaxonomy;
}) {
  const currentVersion = detail.versions.find((version) => version.is_current);
  const pendingApproval = detail.approvals.find((approval) => approval.status === "PENDING");
  const [title, setTitle] = useState(detail.title);
  const [description, setDescription] = useState(detail.description ?? "");
  const [categoryId, setCategoryId] = useState(detail.category_id ?? "");
  const [rightsHolder, setRightsHolder] = useState(detail.rights?.rights_holder ?? "");
  const [licenseType, setLicenseType] = useState(detail.rights?.license_type ?? "");
  const [usageEnd, setUsageEnd] = useState(detail.rights?.usage_end?.slice(0, 10) ?? "");
  const [versionFile, setVersionFile] = useState<File | null>(null);
  const [versionReason, setVersionReason] = useState("");
  const [relationTarget, setRelationTarget] = useState("");
  const [collectionName, setCollectionName] = useState("");

  const previewKind = useMemo(() => {
    if (!currentVersion) return "none";
    if (currentVersion.mime_type.startsWith("image/")) return "image";
    if (currentVersion.mime_type.startsWith("audio/")) return "audio";
    if (currentVersion.mime_type.startsWith("video/")) return "video";
    if (currentVersion.mime_type === "application/pdf") return "pdf";
    return "none";
  }, [currentVersion]);

  return (
    <article className="media-detail">
      <header>
        <div>
          <h3>{detail.title}</h3>
          <p>
            {detail.status} · Version {detail.current_version_number}
          </p>
        </div>
        <span>{detail.approval_status}</span>
      </header>
      <div className="media-preview">
        {previewKind === "image" ? (
          // The private preview requires the browser session cookie; Next image optimization
          // runs server-side and must therefore not proxy this protected URL.
          // eslint-disable-next-line @next/next/no-img-element
          <img alt={`Vorschau ${detail.title}`} src={mediaFileUrl(detail.id)} />
        ) : null}
        {previewKind === "audio" ? <audio controls src={mediaFileUrl(detail.id)} /> : null}
        {previewKind === "video" ? <video controls src={mediaFileUrl(detail.id)} /> : null}
        {previewKind === "pdf" ? (
          <iframe src={mediaFileUrl(detail.id)} title={`PDF ${detail.title}`} />
        ) : null}
      </div>
      <a className="download-link" href={mediaFileUrl(detail.id, true)}>
        Original autorisiert herunterladen
      </a>

      {canWrite ? (
        <div className="detail-block">
          <h4>Fachliche Metadaten</h4>
          <div className="field-grid">
            <label>
              Titel
              <input value={title} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <label>
              Kategorie
              <select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
                <option value="">Keine</option>
                {taxonomy.categories.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Beschreibung
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
          </div>
          <button
            disabled={busy}
            onClick={() =>
              void run(
                () =>
                  mediaCommand(
                    `/api/v1/media-assets/${detail.id}`,
                    {
                      expected_revision: detail.revision,
                      title,
                      description,
                      category_id: categoryId || null,
                      tag_ids: detail.tags.map((tag) => tag.id),
                      business_metadata: currentVersion?.business_metadata ?? {},
                      custom_metadata: {},
                    },
                    "PATCH",
                  ),
                "Metadaten gespeichert",
              )
            }
            type="button"
          >
            Metadaten speichern
          </button>
        </div>
      ) : null}

      <div className="detail-block">
        <h4>Technische Daten</h4>
        <pre>{JSON.stringify(currentVersion?.technical_metadata ?? {}, null, 2)}</pre>
        <p>SHA-256: {currentVersion?.sha256}</p>
      </div>

      {canWrite ? (
        <div className="detail-block">
          <h4>Neue unveränderliche Version</h4>
          <input
            accept=".jpg,.jpeg,.png,.webp,.pdf,.mp3,.wav,.mp4"
            type="file"
            onChange={(event) => setVersionFile(event.target.files?.[0] ?? null)}
          />
          <input
            placeholder="Änderungsgrund"
            value={versionReason}
            onChange={(event) => setVersionReason(event.target.value)}
          />
          <button
            disabled={busy || !versionFile || !versionReason}
            onClick={() =>
              versionFile
                ? void run(
                    () =>
                      uploadMediaVersion(detail.id, detail.revision, versionReason, versionFile),
                    "Neue Version gespeichert; Freigabe nicht übernommen",
                  )
                : undefined
            }
            type="button"
          >
            Version hochladen
          </button>
        </div>
      ) : null}

      <div className="detail-block">
        <h4>Versionen</h4>
        {detail.versions.map((version) => (
          <p key={version.id}>
            v{version.version_number} · {version.original_filename} · {version.approval_status} ·{" "}
            <a href={mediaFileUrl(detail.id, true, version.id)}>Download</a>
          </p>
        ))}
      </div>

      {canWrite ? (
        <div className="detail-block">
          <h4>Rechte und Lizenz</h4>
          <div className="field-grid">
            <label>
              Rechteinhaber
              <input
                value={rightsHolder}
                onChange={(event) => setRightsHolder(event.target.value)}
              />
            </label>
            <label>
              Lizenzart
              <input value={licenseType} onChange={(event) => setLicenseType(event.target.value)} />
            </label>
            <label>
              Nutzungsende
              <input
                type="date"
                value={usageEnd}
                onChange={(event) => setUsageEnd(event.target.value)}
              />
            </label>
          </div>
          <button
            disabled={busy || !rightsHolder || !licenseType}
            onClick={() =>
              void run(
                () =>
                  mediaCommand(
                    `/api/v1/media-assets/${detail.id}/rights`,
                    {
                      expected_revision: detail.revision,
                      rights_holder: rightsHolder,
                      license_type: licenseType,
                      usage_end: usageEnd ? new Date(`${usageEnd}T23:59:59Z`).toISOString() : null,
                      allowed_uses: ["INTERNAL"],
                      allowed_regions: ["DE"],
                      allowed_channels: ["INTERNAL"],
                      attribution_required: false,
                      editing_allowed: false,
                      redistribution_allowed: false,
                    },
                    "PUT",
                  ),
                "Rechte zur Prüfung gespeichert",
              )
            }
            type="button"
          >
            Rechte speichern
          </button>
        </div>
      ) : null}
      {canReview && detail.rights?.review_status === "PENDING" ? (
        <div className="action-grid">
          <button
            disabled={busy}
            onClick={() =>
              void run(
                () =>
                  mediaCommand(`/api/v1/media-assets/${detail.id}/rights/review`, {
                    approve: true,
                    reason: "Rechte geprüft",
                  }),
                "Rechte freigegeben",
              )
            }
            type="button"
          >
            Rechte freigeben
          </button>
          <button
            disabled={busy}
            onClick={() =>
              void run(
                () =>
                  mediaCommand(`/api/v1/media-assets/${detail.id}/rights/review`, {
                    approve: false,
                    reason: "Rechteprüfung abgelehnt",
                  }),
                "Rechte abgelehnt",
              )
            }
            type="button"
          >
            Rechte ablehnen
          </button>
        </div>
      ) : null}

      <div className="action-grid">
        {canWrite && detail.rights?.review_status === "APPROVED" && !pendingApproval ? (
          <button
            disabled={busy}
            onClick={() =>
              void run(
                () => mediaCommand(`/api/v1/media-assets/${detail.id}/approvals`),
                "Freigabe angefordert",
              )
            }
            type="button"
          >
            Freigabe anfordern
          </button>
        ) : null}
        {canReview && pendingApproval ? (
          <>
            <button
              disabled={busy}
              onClick={() =>
                void run(
                  () =>
                    mediaCommand(
                      `/api/v1/media-assets/${detail.id}/approvals/${pendingApproval.id}/resolve`,
                      { approve: true, reason: "Inhalt geprüft" },
                    ),
                  "Medium freigegeben",
                )
              }
              type="button"
            >
              Freigeben
            </button>
            <button
              disabled={busy}
              onClick={() =>
                void run(
                  () =>
                    mediaCommand(
                      `/api/v1/media-assets/${detail.id}/approvals/${pendingApproval.id}/resolve`,
                      { approve: false, reason: "Änderungen erforderlich" },
                    ),
                  "Medium abgelehnt",
                )
              }
              type="button"
            >
              Ablehnen
            </button>
          </>
        ) : null}
      </div>

      {canWrite && currentVersion ? (
        <div className="detail-block">
          <h4>Varianten und Beziehungen</h4>
          <button
            disabled={busy}
            onClick={() =>
              void run(
                () =>
                  mediaCommand(`/api/v1/media-assets/${detail.id}/variants`, {
                    version_id: currentVersion.id,
                    variant_type: "THUMBNAIL",
                    technical_properties: { manual: true },
                  }),
                "Variante registriert",
              )
            }
            type="button"
          >
            Thumbnail-Variante registrieren
          </button>
          <select
            value={relationTarget}
            onChange={(event) => setRelationTarget(event.target.value)}
          >
            <option value="">Zielmedium</option>
            {items
              .filter((item) => item.id !== detail.id)
              .map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                </option>
              ))}
          </select>
          <button
            disabled={busy || !relationTarget}
            onClick={() =>
              void run(
                () =>
                  mediaCommand(`/api/v1/media-assets/${detail.id}/relations`, {
                    target_asset_id: relationTarget,
                    relation_type: "LINKED_WITH",
                  }),
                "Beziehung gespeichert",
              )
            }
            type="button"
          >
            Verknüpfen
          </button>
        </div>
      ) : null}

      {canWrite ? (
        <div className="detail-block">
          <h4>Sammlungen</h4>
          <input
            placeholder="Neue Sammlung"
            value={collectionName}
            onChange={(event) => setCollectionName(event.target.value)}
          />
          <button
            disabled={busy || !collectionName}
            onClick={() =>
              void run(
                () =>
                  mediaCommand("/api/v1/media-collections", {
                    name: collectionName,
                    description: "Interne Mediensammlung",
                    visibility: "TENANT",
                  }),
                "Sammlung erstellt",
              )
            }
            type="button"
          >
            Sammlung erstellen
          </button>
          {collections.map((collection) => (
            <button
              disabled={busy || collection.items.some((item) => item.asset_id === detail.id)}
              key={collection.id}
              onClick={() =>
                void run(
                  () =>
                    mediaCommand(`/api/v1/media-collections/${collection.id}/items`, {
                      asset_id: detail.id,
                    }),
                  "Medium zur Sammlung hinzugefügt",
                )
              }
              type="button"
            >
              Zu {collection.name}
            </button>
          ))}
        </div>
      ) : null}

      <div className="action-grid">
        {canWrite && !detail.archived ? (
          <button
            disabled={busy}
            onClick={() =>
              void run(
                () =>
                  mediaCommand(`/api/v1/media-assets/${detail.id}/archive`, {
                    expected_revision: detail.revision,
                  }),
                "Medium archiviert",
              )
            }
            type="button"
          >
            Archivieren
          </button>
        ) : null}
        {canWrite ? (
          <button
            disabled={busy}
            onClick={() =>
              void run(
                () =>
                  mediaCommand(`/api/v1/media-assets/${detail.id}/deletion-requests`, {
                    expected_revision: detail.revision,
                    reason: "Kontrollierte Löschprüfung",
                  }),
                "Löschung beantragt; physische Löschung noch gesperrt",
              )
            }
            type="button"
          >
            Löschung beantragen
          </button>
        ) : null}
        {canAdmin ? (
          <span>Löschfreigabe erfolgt ausschließlich für einen konkreten Antrag.</span>
        ) : null}
      </div>

      <div className="detail-block">
        <h4>Varianten</h4>
        {detail.variants.map((item) => (
          <p key={item.id}>
            {item.variant_type} · {item.generation_status}
          </p>
        ))}
      </div>
      <div className="detail-block">
        <h4>Beziehungen</h4>
        {detail.relations.map((item) => (
          <p key={item.id}>
            {item.relation_type}: {item.source_asset_id} → {item.target_asset_id}
          </p>
        ))}
      </div>
      <div className="detail-block">
        <h4>Audit</h4>
        {detail.audit.map((item) => (
          <p key={item.id}>
            {new Date(item.created_at).toLocaleString("de-DE")} · {item.event_type}
          </p>
        ))}
      </div>
    </article>
  );
}
