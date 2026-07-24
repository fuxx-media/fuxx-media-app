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
const MEDIA_PAGE_SIZE = 12;

export function MediaWorkspace({ user }: Props) {
  const [items, setItems] = useState<MediaAssetSummary[]>([]);
  const [detail, setDetail] = useState<MediaAssetDetail | null>(null);
  const [taxonomy, setTaxonomy] = useState<MediaTaxonomy>({ categories: [], tags: [] });
  const [collections, setCollections] = useState<MediaCollection[]>([]);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [mediaTypeFilter, setMediaTypeFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [rightsFilter, setRightsFilter] = useState("");
  const [sort, setSort] = useState("updated_desc");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [viewMode, setViewMode] = useState<"list" | "cards">("cards");
  const [message, setMessage] = useState("Mediathek wird geladen …");
  const [busy, setBusy] = useState(false);
  const canWrite = user.roles.some((role) => role === "ADMIN" || role === "BACKOFFICE");
  const canReview = user.roles.some((role) => role === "ADMIN" || role === "REVIEWER");
  const canAdmin = user.roles.includes("ADMIN");

  const reload = useCallback(
    async (targetPage = page) => {
      const [assets, taxonomyResult, collectionResult] = await Promise.all([
        fetchMediaAssets({
          query,
          page: targetPage,
          pageSize: MEDIA_PAGE_SIZE,
          status: statusFilter,
          mediaType: mediaTypeFilter,
          categoryId: categoryFilter,
          rightsStatus: rightsFilter,
          sort,
        }),
        fetchMediaTaxonomy(),
        fetchMediaCollections(),
      ]);
      setItems(assets.items);
      setPage(assets.page);
      setTotal(assets.total);
      setTaxonomy(taxonomyResult);
      setCollections(collectionResult.items);
      if (detail) setDetail(await fetchMediaAsset(detail.id));
      setMessage(`${assets.total} Medienobjekte`);
    },
    [categoryFilter, detail, mediaTypeFilter, page, query, rightsFilter, sort, statusFilter],
  );

  useEffect(() => {
    void Promise.all([
      fetchMediaAssets({ pageSize: MEDIA_PAGE_SIZE }),
      fetchMediaTaxonomy(),
      fetchMediaCollections(),
    ])
      .then(([assets, taxonomyResult, collectionResult]) => {
        setItems(assets.items);
        setTotal(assets.total);
        setTaxonomy(taxonomyResult);
        setCollections(collectionResult.items);
        setMessage(`${assets.total} Medienobjekte`);
      })
      .catch((error) =>
        setMessage(error instanceof Error ? error.message : "Laden fehlgeschlagen"),
      );
  }, []);

  async function run(
    action: () => Promise<unknown>,
    success: string | ((result: unknown) => string),
  ) {
    setBusy(true);
    try {
      const result = await action();
      await reload();
      setMessage(typeof success === "string" ? success : success(result));
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
        <label>
          Status
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">Alle</option>
            {[
              "DRAFT",
              "QUARANTINED",
              "TECHNICAL_REVIEW",
              "CONTENT_REVIEW",
              "RIGHTS_REVIEW",
              "CHANGES_REQUESTED",
              "READY",
              "ARCHIVED",
              "DELETION_PENDING",
            ].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          Medientyp
          <select
            value={mediaTypeFilter}
            onChange={(event) => setMediaTypeFilter(event.target.value)}
          >
            <option value="">Alle</option>
            {["IMAGE", "DOCUMENT", "AUDIO", "VIDEO"].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          Kategorie
          <select
            value={categoryFilter}
            onChange={(event) => setCategoryFilter(event.target.value)}
          >
            <option value="">Alle</option>
            {taxonomy.categories.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Rechte
          <select value={rightsFilter} onChange={(event) => setRightsFilter(event.target.value)}>
            <option value="">Alle</option>
            {["PENDING", "APPROVED", "REJECTED", "EXPIRED", "CONFLICT"].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          Sortierung
          <select value={sort} onChange={(event) => setSort(event.target.value)}>
            <option value="updated_desc">Zuletzt geändert</option>
            <option value="updated_asc">Älteste Änderung</option>
            <option value="created_desc">Neueste Uploads</option>
            <option value="title_asc">Titel A–Z</option>
          </select>
        </label>
        <button disabled={busy} onClick={() => void reload(1)} type="button">
          Suchen
        </button>
        <button
          disabled={busy}
          onClick={() => setViewMode(viewMode === "cards" ? "list" : "cards")}
          type="button"
        >
          {viewMode === "cards" ? "Listenansicht" : "Kartenansicht"}
        </button>
      </div>

      {canAdmin ? <TaxonomyPanel busy={busy} run={run} taxonomy={taxonomy} /> : null}
      {canWrite ? <UploadPanel busy={busy} run={run} /> : null}

      <div className="media-layout">
        <div className={`media-list ${viewMode}`} aria-label="Medienliste">
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
          <div className="media-pagination">
            <button
              disabled={busy || page <= 1}
              onClick={() => void reload(page - 1)}
              type="button"
            >
              Zurück
            </button>
            <span>
              Seite {page} von {Math.max(1, Math.ceil(total / MEDIA_PAGE_SIZE))}
            </span>
            <button
              disabled={busy || page >= Math.ceil(total / MEDIA_PAGE_SIZE)}
              onClick={() => void reload(page + 1)}
              type="button"
            >
              Weiter
            </button>
          </div>
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
  const [progress, setProgress] = useState(0);
  const [controller, setController] = useState<AbortController | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    const uploadController = new AbortController();
    setController(uploadController);
    setProgress(0);
    try {
      await run(
        async () => {
          const result = await uploadMediaAsset(title, description, file, {
            onProgress: setProgress,
            signal: uploadController.signal,
          });
          setTitle("");
          setDescription("");
          setFile(null);
          return result;
        },
        (result) => {
          const upload = result as { duplicate_binary: boolean; quarantined: boolean };
          if (upload.quarantined) return "Upload gespeichert und zur Quarantäneprüfung markiert";
          if (upload.duplicate_binary) return "Upload gespeichert; Binärduplikat ohne Doppelablage";
          return "Upload gespeichert und technische Prüfung eingeplant";
        },
      );
    } finally {
      setController(null);
    }
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
      {controller ? (
        <button onClick={() => controller.abort()} type="button">
          Upload abbrechen
        </button>
      ) : null}
      <progress max={100} value={progress}>
        {progress}%
      </progress>
    </form>
  );
}

type RunAction = (
  action: () => Promise<unknown>,
  success: string | ((result: unknown) => string),
) => Promise<void>;

function TaxonomyPanel({
  busy,
  run,
  taxonomy,
}: {
  busy: boolean;
  run: RunAction;
  taxonomy: MediaTaxonomy;
}) {
  const [categoryName, setCategoryName] = useState("");
  const [parentId, setParentId] = useState("");
  const [tagName, setTagName] = useState("");
  const [synonyms, setSynonyms] = useState("");
  return (
    <details className="detail-block">
      <summary>Taxonomie verwalten</summary>
      <div className="field-grid">
        <input
          placeholder="Kategorie"
          value={categoryName}
          onChange={(event) => setCategoryName(event.target.value)}
        />
        <select value={parentId} onChange={(event) => setParentId(event.target.value)}>
          <option value="">Keine Oberkategorie</option>
          {taxonomy.categories.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        <button
          disabled={busy || !categoryName}
          onClick={() =>
            void run(
              () =>
                mediaCommand("/api/v1/media-categories", {
                  name: categoryName,
                  slug: `${categoryName.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-${Date.now()}`,
                  parent_id: parentId || null,
                }),
              "Kategorie angelegt",
            )
          }
          type="button"
        >
          Kategorie anlegen
        </button>
        <input
          placeholder="Schlagwort"
          value={tagName}
          onChange={(event) => setTagName(event.target.value)}
        />
        <input
          placeholder="Synonyme, kommagetrennt"
          value={synonyms}
          onChange={(event) => setSynonyms(event.target.value)}
        />
        <button
          disabled={busy || !tagName}
          onClick={() =>
            void run(
              () =>
                mediaCommand("/api/v1/media-tags", {
                  name: tagName,
                  synonyms: synonyms
                    .split(",")
                    .map((item) => item.trim())
                    .filter(Boolean),
                }),
              "Schlagwort angelegt",
            )
          }
          type="button"
        >
          Schlagwort anlegen
        </button>
      </div>
    </details>
  );
}

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
  const pendingDeletion = detail.deletion_requests.find(
    (request) => request.status === "REQUESTED",
  );
  const [title, setTitle] = useState(detail.title);
  const [description, setDescription] = useState(detail.description ?? "");
  const [categoryId, setCategoryId] = useState(detail.category_id ?? "");
  const [tagIds, setTagIds] = useState(detail.tags.map((tag) => tag.id));
  const [rightsHolder, setRightsHolder] = useState(detail.rights?.rights_holder ?? "");
  const [licenseType, setLicenseType] = useState(detail.rights?.license_type ?? "");
  const [usageEnd, setUsageEnd] = useState(detail.rights?.usage_end?.slice(0, 10) ?? "");
  const [rightsRestrictions, setRightsRestrictions] = useState(detail.rights?.restrictions ?? "");
  const [proofAssetId, setProofAssetId] = useState(detail.rights?.proof_media_asset_id ?? "");
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
            <fieldset>
              <legend>Schlagwörter</legend>
              {taxonomy.tags.map((tag) => (
                <label key={tag.id}>
                  <input
                    checked={tagIds.includes(tag.id)}
                    type="checkbox"
                    onChange={(event) =>
                      setTagIds((current) =>
                        event.target.checked
                          ? [...new Set([...current, tag.id])]
                          : current.filter((id) => id !== tag.id),
                      )
                    }
                  />
                  {tag.name}
                </label>
              ))}
            </fieldset>
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
                      tag_ids: tagIds,
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
        <details>
          <summary>Technische Versionsstände vergleichen</summary>
          {detail.versions.map((version) => (
            <div key={`compare-${version.id}`}>
              <strong>Version {version.version_number}</strong>
              <p>
                {version.mime_type} · {version.size_bytes} Bytes · {version.sha256}
              </p>
              <pre>{JSON.stringify(version.technical_metadata, null, 2)}</pre>
            </div>
          ))}
        </details>
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
            <label>
              Einschränkungen
              <textarea
                value={rightsRestrictions}
                onChange={(event) => setRightsRestrictions(event.target.value)}
              />
            </label>
            <label>
              Nachweisdokument
              <select
                value={proofAssetId}
                onChange={(event) => setProofAssetId(event.target.value)}
              >
                <option value="">Kein Nachweis verknüpft</option>
                {items
                  .filter((item) => item.id !== detail.id)
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.title}
                    </option>
                  ))}
              </select>
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
                      restrictions: rightsRestrictions || null,
                      proof_media_asset_id: proofAssetId || null,
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
            <CollectionEditor
              assetId={detail.id}
              busy={busy}
              collection={collection}
              key={collection.id}
              run={run}
            />
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
        {canAdmin && pendingDeletion ? (
          <button
            disabled={busy}
            onClick={() =>
              void run(
                () =>
                  mediaCommand(`/api/v1/media-assets/${detail.id}/deletion-approvals`, {
                    request_id: pendingDeletion.id,
                    reason: "Referenzen und Aufbewahrung geprüft",
                  }),
                "Löschung freigegeben und Worker-Prüfung eingeplant",
              )
            }
            type="button"
          >
            Löschantrag freigeben
          </button>
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

function CollectionEditor({
  assetId,
  busy,
  collection,
  run,
}: {
  assetId: string;
  busy: boolean;
  collection: MediaCollection;
  run: RunAction;
}) {
  const [name, setName] = useState(collection.name);
  const [description, setDescription] = useState(collection.description ?? "");
  const orderedIds = [...collection.items]
    .sort((left, right) => left.position - right.position)
    .map((item) => item.asset_id);
  const position = orderedIds.indexOf(assetId);
  const isMember = position >= 0;
  function move(delta: number) {
    const nextPosition = position + delta;
    if (position < 0 || nextPosition < 0 || nextPosition >= orderedIds.length) return;
    const nextOrder = [...orderedIds];
    const currentId = nextOrder[position];
    const targetId = nextOrder[nextPosition];
    if (currentId === undefined || targetId === undefined) return;
    nextOrder[position] = targetId;
    nextOrder[nextPosition] = currentId;
    void run(
      () =>
        mediaCommand(
          `/api/v1/media-collections/${collection.id}/order`,
          {
            asset_ids: nextOrder,
          },
          "PUT",
        ),
      "Sammlungsreihenfolge gespeichert",
    );
  }
  return (
    <div className="collection-editor">
      <input value={name} onChange={(event) => setName(event.target.value)} />
      <input
        placeholder="Beschreibung"
        value={description}
        onChange={(event) => setDescription(event.target.value)}
      />
      <button
        disabled={busy || !name}
        onClick={() =>
          void run(
            () =>
              mediaCommand(
                `/api/v1/media-collections/${collection.id}`,
                {
                  name,
                  description: description || null,
                  visibility: collection.visibility,
                  status: collection.status,
                },
                "PATCH",
              ),
            "Sammlung bearbeitet",
          )
        }
        type="button"
      >
        Speichern
      </button>
      {!isMember ? (
        <button
          disabled={busy}
          onClick={() =>
            void run(
              () =>
                mediaCommand(`/api/v1/media-collections/${collection.id}/items`, {
                  asset_id: assetId,
                }),
              "Medium zur Sammlung hinzugefügt",
            )
          }
          type="button"
        >
          Hinzufügen
        </button>
      ) : (
        <>
          <button disabled={busy || position === 0} onClick={() => move(-1)} type="button">
            Nach vorn
          </button>
          <button
            disabled={busy || position === orderedIds.length - 1}
            onClick={() => move(1)}
            type="button"
          >
            Nach hinten
          </button>
          <button
            disabled={busy}
            onClick={() =>
              void run(
                () =>
                  mediaCommand(
                    `/api/v1/media-collections/${collection.id}/items/${assetId}`,
                    {},
                    "DELETE",
                  ),
                "Medium aus Sammlung entfernt",
              )
            }
            type="button"
          >
            Entfernen
          </button>
        </>
      )}
    </div>
  );
}
