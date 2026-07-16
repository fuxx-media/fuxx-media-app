"""Establish the Phase 0.1 migration baseline.

Revision ID: 0001_phase_zero_foundation
Revises: None
"""

from collections.abc import Sequence

revision: str = "0001_phase_zero_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Business tables intentionally start in Phase 0.2."""


def downgrade() -> None:
    """The empty baseline has no business schema to remove."""

