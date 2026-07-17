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

export type RoleName = "ADMIN" | "BACKOFFICE" | "REVIEWER" | "SYSTEM_WORKER";

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
