"""Baseline: the schema previously created by Base.metadata.create_all

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inspections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("image_path", sa.String(500), nullable=False),
        sa.Column("annotated_image_path", sa.String(500), nullable=True),
        sa.Column("timestamp", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("latitude", sa.Float, nullable=True),
        sa.Column("longitude", sa.Float, nullable=True),
        sa.Column("damage_count", sa.Integer, nullable=False),
        sa.Column("overall_severity", sa.String(20), nullable=False),
        sa.Column("priority_score", sa.Float, nullable=False),
    )
    op.create_table(
        "damages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("inspection_id", sa.Integer, sa.ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("class", sa.String(40), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("area", sa.Float, nullable=False),
        sa.Column("length", sa.Float, nullable=False),
        sa.Column("width", sa.Float, nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("severity_score", sa.Float, nullable=False),
        sa.Column("bbox", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("damages")
    op.drop_table("inspections")
