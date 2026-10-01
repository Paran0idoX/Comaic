"""增加人物参考图三件套生成任务、运行和产物。"""

from alembic import op
import sqlalchemy as sa


revision = "0006_character_reference_generation"
down_revision = "0005_consistency_evaluation"
branch_labels = None
depends_on = None


TS = sa.String(length=40)


def upgrade() -> None:
    op.create_table(
        "character_reference_generation_task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("comic_project.id"),
            nullable=False,
        ),
        sa.Column(
            "outline_character_id",
            sa.Integer(),
            sa.ForeignKey("outline_character.id"),
            nullable=False,
        ),
        sa.Column(
            "tool_preset_id",
            sa.Integer(),
            sa.ForeignKey("image_generation_tool_preset.id"),
            nullable=False,
        ),
        sa.Column(
            "style_profile_id",
            sa.Integer(),
            sa.ForeignKey("style_profile.id"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("prompt_type", sa.String(length=64), nullable=False),
        sa.Column("prompt_snapshot_json", sa.Text(), nullable=False),
        sa.Column("progress_json", sa.Text(), nullable=False),
        sa.Column("approved_candidate_index", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("heartbeat_at", TS, nullable=True),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    for column in (
        "project_id",
        "outline_character_id",
        "tool_preset_id",
        "style_profile_id",
        "status",
    ):
        op.create_index(
            f"ix_character_reference_generation_task_{column}",
            "character_reference_generation_task",
            [column],
        )

    op.create_table(
        "character_reference_generation_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("character_reference_generation_task.id"),
            nullable=False,
        ),
        sa.Column("candidate_index", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("prompt_type", sa.String(length=64), nullable=False),
        sa.Column("positive_prompt", sa.Text(), nullable=False),
        sa.Column("negative_prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("review_status", sa.String(length=64), nullable=False),
        sa.Column("seed_applied", sa.Boolean(), nullable=False),
        sa.Column("external_request_id", sa.String(length=255), nullable=True),
        sa.Column("workflow_json", sa.Text(), nullable=True),
        sa.Column("workflow_hash", sa.String(length=64), nullable=True),
        sa.Column("bindings_json", sa.Text(), nullable=False),
        sa.Column("degradation_json", sa.Text(), nullable=False),
        sa.Column("applied_spec_json", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.UniqueConstraint(
            "task_id",
            "candidate_index",
            "role",
            name="uq_character_reference_run_candidate_role",
        ),
    )
    for column in ("task_id", "role", "provider", "status", "review_status"):
        op.create_index(
            f"ix_character_reference_generation_run_{column}",
            "character_reference_generation_run",
            [column],
        )
    op.create_index(
        "ix_character_reference_generation_run_external_request_id",
        "character_reference_generation_run",
        ["external_request_id"],
    )

    op.create_table(
        "character_reference_image",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("character_reference_generation_run.id"),
            nullable=False,
        ),
        sa.Column("artifact_index", sa.Integer(), nullable=False),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column(
            "promoted_asset_id",
            sa.Integer(),
            sa.ForeignKey("visual_asset.id"),
            nullable=True,
            unique=True,
        ),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "artifact_index",
            name="uq_character_reference_image_artifact",
        ),
    )
    op.create_index(
        "ix_character_reference_image_run_id",
        "character_reference_image",
        ["run_id"],
    )
    op.create_index(
        "ix_character_reference_image_sha256",
        "character_reference_image",
        ["sha256"],
    )


def downgrade() -> None:
    op.drop_table("character_reference_image")
    op.drop_table("character_reference_generation_run")
    op.drop_table("character_reference_generation_task")
