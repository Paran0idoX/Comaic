"""保存按来源复用的参考图视觉摘要，不回写角色或场景原文。"""

from alembic import op
import sqlalchemy as sa

revision = "0009_reference_visual_profiles"
down_revision = "0008_remove_visual_anchors"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("reference_visual_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("comic_project.id"), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("project_id", "kind", "owner_id", name="uq_reference_profile_owner"))
    op.create_index("ix_reference_visual_profile_project_id", "reference_visual_profile", ["project_id"])


def downgrade():
    op.drop_table("reference_visual_profile")
