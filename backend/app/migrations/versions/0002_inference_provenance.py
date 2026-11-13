"""Record which detector produced each inspection

Rows that predate this migration get inference_mode 'unknown': nothing was
recorded for them, so no mode is claimed on their behalf.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inspections", sa.Column("inference_mode", sa.String(20), nullable=False, server_default="unknown"))
    op.add_column("inspections", sa.Column("model_name", sa.String(120), nullable=True))
    op.add_column("inspections", sa.Column("model_version", sa.String(64), nullable=True))
    op.create_index("ix_damages_inspection_id", "damages", ["inspection_id"])


def downgrade() -> None:
    op.drop_index("ix_damages_inspection_id", table_name="damages")
    op.drop_column("inspections", "model_version")
    op.drop_column("inspections", "model_name")
    op.drop_column("inspections", "inference_mode")
