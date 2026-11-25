"""turn runs into a job queue: request payload, lease, attempts, cancel flag

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("request", JSONB()))
    op.add_column("runs", sa.Column("claimed_by", sa.Text()))
    op.add_column("runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
    op.add_column("runs", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(
        "runs", sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default="false")
    )
    op.create_index("runs_queue_idx", "runs", ["status", "lease_expires_at"])
