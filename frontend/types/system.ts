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
