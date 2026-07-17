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
