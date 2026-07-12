"""持久化 ImageSpec 批量编译进度与失败页。"""

from alembic import op
import sqlalchemy as sa


revision = "0004_image_spec_compilation"
down_revision = "0003_prompt_types"
branch_labels = None
depends_on = None


TS = sa.String(length=40)


def upgrade() -> None:
    op.create_table(
        "image_spec_compilation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "script_task_id",
            sa.Integer(),
            sa.ForeignKey("script_generation_task.id"),
            nullable=False,
        ),
        sa.Column(
            "continuity_compilation_id",
            sa.Integer(),
            sa.ForeignKey("continuity_compilation.id"),
            nullable=False,
        ),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("generation_mode", sa.String(length=64), nullable=False),
        sa.Column("total_pages", sa.Integer(), nullable=False),
        sa.Column("completed_pages", sa.Integer(), nullable=False),
        sa.Column("total_specs", sa.Integer(), nullable=False),
        sa.Column("completed_specs", sa.Integer(), nullable=False),
        sa.Column("failed_pages_json", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    for column in (
        "script_task_id",
        "continuity_compilation_id",
        "source_hash",
        "status",
        "generation_mode",
    ):
        op.create_index(
            f"ix_image_spec_compilation_{column}",
            "image_spec_compilation",
            [column],
        )


def downgrade() -> None:
    op.drop_table("image_spec_compilation")
