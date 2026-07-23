export type ReadinessResponse = {
  dependencies: {
    minio: boolean;
    postgres: boolean;
  };
  status: "ready" | "not_ready";
};

export type VersionResponse = {
  phase: string;
  name: string;
  version: string;
};

export type RoleName = "ADMIN" | "BACKOFFICE" | "REVIEWER" | "READER" | "SYSTEM_WORKER";

export type LoginRequest = {
  tenant_slug: string;
  email: string;
  password: string;
};

export type AuthenticatedUser = {
  user_id: string;
  tenant_id: string;
  email: string;
  roles: RoleName[];
};

export type LoginResponse = AuthenticatedUser & {
  expires_at: string;
  csrf_token: string;
};

export type CasePriority = "LOW" | "NORMAL" | "HIGH" | "URGENT";
export type CaseStatus =
  "OPEN" | "IN_PROGRESS" | "DEFERRED" | "AWAITING_APPROVAL" | "APPROVED" | "REJECTED" | "COMPLETED";

export type CaseSummary = {
  id: string;
  tenant_id: string;
  title: string;
  workflow_state: string;
  business_status: CaseStatus;
  category: string | null;
  priority: CasePriority;
  version: number;
  assigned_to: string | null;
  claimed_by: string | null;
  claim_expires_at: string | null;
  due_at: string | null;
};

export type CaseDetail = CaseSummary & {
  attachments: Array<{
    id: string;
    stored_file_id: string;
    filename: string;
    sha256: string;
    mime_type: string;
    size_bytes: number;
  }>;
  checklist: Array<{
    id: string;
    title: string;
    required: boolean;
    completed_at: string | null;
  }>;
  notes: Array<{ id: string; revision: number; content: string; created_at: string }>;
  evidence: Array<{
    id: string;
    revision: number;
    source: string;
    verification_status: string;
    created_at: string;
  }>;
  approvals: Array<{
    id: string;
    revision: number;
    status: "PENDING" | "APPROVED" | "REJECTED";
    requested_by: string;
    claimed_by: string | null;
    reason: string | null;
    invalidated_at: string | null;
  }>;
  revisions: Array<{
    id: string;
    revision: number;
    change_type: string;
    created_at: string;
  }>;
  audit_events: Array<{
    id: string;
    event_type: string;
    created_at: string;
  }>;
};

export type ProviderCapability = {
  id: string;
  name: string;
  operation: string;
  required_fields: string[];
  enabled: boolean;
};

export type ProviderConfiguration = {
  id: string;
  name: string;
  provider_type: string;
  enabled: boolean;
  settings: Record<string, unknown>;
  dry_run_enabled: boolean;
  production_enabled: boolean;
  callback_enabled: boolean;
  secret_reference: {
    id: string;
    name: string;
    environment_variable: string;
    configured: boolean;
  } | null;
  signature_profile: {
    id: string;
    name: string;
    algorithm: string;
    timestamp_tolerance_seconds: number;
  } | null;
  capabilities: ProviderCapability[];
};

export type ProviderFeatureFlags = {
  global_integration_enabled: boolean;
  dry_run_enabled: boolean;
  production_execution_enabled: boolean;
  callback_intake_enabled: boolean;
};

export type ProviderListResponse = {
  items: ProviderConfiguration[];
  feature_flags: ProviderFeatureFlags;
  productive_execution_visible: boolean;
};

export type ExecutionSummary = {
  id: string;
  job_id: string;
  job_revision: number;
  provider_configuration_id: string;
  capability_id: string;
  operation: string;
  correlation_id: string;
  status: string;
  dry_run: boolean;
  external_effect: boolean;
  prepared_payload: Record<string, unknown>;
  max_attempts: number;
  discard_reason: string | null;
  created_at: string;
  completed_at: string | null;
};

export type ExecutionDetail = ExecutionSummary & {
  outbox: Array<{
    id: string;
    sequence: number;
    status: string;
    attempts: number;
    last_error: string | null;
  }>;
  attempts: Array<{
    id: string;
    attempt_number: number;
    status: string;
    error_classification: string | null;
    error_message: string | null;
    response_payload: Record<string, unknown> | null;
  }>;
  responses: Array<{
    provider_status: string;
    normalized_status: string;
    payload: Record<string, unknown>;
  }>;
  retry_plans: Array<{
    attempt_number: number;
    backoff_seconds: number;
    classification: string;
    status: string;
  }>;
  artifacts: Array<{ kind: string; sha256: string; metadata: Record<string, unknown> }>;
  dry_run_result: {
    valid: boolean;
    masked_payload: Record<string, unknown>;
    validation_errors: string[];
    external_effect: boolean;
  } | null;
  audit_events: Array<{
    id: string;
    event_type: string;
    payload: Record<string, unknown>;
    created_at: string;
  }>;
};

export type MediaAssetSummary = {
  id: string;
  tenant_id: string;
  title: string;
  media_type: string;
  status: string;
  technical_status: string;
  approval_status: string;
  storage_status: string;
  current_version_number: number;
  category_id: string | null;
  archived: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type MediaAssetDetail = MediaAssetSummary & {
  description: string | null;
  revision: number;
  assigned_to: string | null;
  retention_status: string;
  confidentiality: string;
  deletion_locked: boolean;
  tags: Array<{ id: string; name: string }>;
  versions: Array<{
    id: string;
    version_number: number;
    file_id: string;
    original_filename: string;
    mime_type: string;
    size_bytes: number;
    sha256: string;
    change_reason: string;
    approval_status: string;
    is_current: boolean;
    created_at: string;
    technical_metadata: Record<string, unknown>;
    business_metadata: Record<string, unknown>;
  }>;
  variants: Array<{
    id: string;
    source_version_id: string;
    variant_type: string;
    technical_properties: Record<string, unknown>;
    generation_status: string;
    generation_source: string;
  }>;
  relations: Array<{
    id: string;
    source_asset_id: string;
    target_asset_id: string;
    relation_type: string;
  }>;
  rights: null | {
    id: string;
    rights_holder: string;
    license_type: string;
    usage_start: string | null;
    usage_end: string | null;
    allowed_uses: string[];
    allowed_regions: string[];
    allowed_channels: string[];
    attribution_required: boolean;
    editing_allowed: boolean;
    redistribution_allowed: boolean;
    restrictions: string | null;
    proof_media_asset_id: string | null;
    review_status: string;
    review_reason: string | null;
  };
  approvals: Array<{
    id: string;
    media_version_id: string;
    requested_by: string;
    resolved_by: string | null;
    status: string;
    reason: string | null;
    created_at: string;
  }>;
  deletion_requests: Array<{
    id: string;
    requested_by: string;
    approved_by: string | null;
    reason: string;
    status: string;
    requested_at: string;
    approved_at: string | null;
  }>;
  audit: Array<{
    id: string;
    event_type: string;
    payload: Record<string, unknown>;
    created_at: string;
  }>;
};

export type MediaTaxonomy = {
  categories: Array<{ id: string; parent_id: string | null; name: string; slug: string }>;
  tags: Array<{ id: string; name: string; synonyms: string[] }>;
};

export type MediaCollection = {
  id: string;
  name: string;
  description: string | null;
  visibility: string;
  status: string;
  items: Array<{ asset_id: string; position: number }>;
};
