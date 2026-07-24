# ADR 0006: Private versioned media lifecycle

## Status

Accepted for Hauptblock 6.

## Context

FUXX MEDIA needs an internal media core that survives later distribution choices without depending
on another business system. Binaries are not transactional with
PostgreSQL, and technical validity, rights, human approval and storage safety are distinct facts.

## Decision

Use `MediaAsset` as the tenant aggregate and append immutable `MediaVersion` rows. Store each tenant,
SHA-256 and byte-length binary once in a private MinIO key and reference it through `MediaFile`.
Validate signatures and extract bounded metadata locally. Keep business, technical, approval,
storage and retention states separate. Serve content only through authenticated API routes.

New versions require new rights and approval. Physical deletion follows a reasoned request, Admin
approval and a persistent worker task; shared binaries, holds and active relations prevent purge.
Metadata extraction and preview registration perform no external call. Hauptblock 6 has no publishing
surface and no public media link.

## Consequences

Database and object-store backup/restore must be coordinated. MinIO cannot join the SQL transaction,
so failed first-time registration uses object compensation. PostgreSQL remains authoritative for
identity, permissions, lifecycle and audit; object storage contains only private bytes.
