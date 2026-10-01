"""增加图片批次轨道和 ViStoryBench 一致性评估。"""

from alembic import op
import sqlalchemy as sa


revision = "0005_consistency_evaluation"
down_revision = "0004_image_spec_compilation"
branch_labels = None
depends_on = None


TS = sa.String(length=40)


def upgrade() -> None:
    with op.batch_alter_table("outline_character") as batch_op:
        batch_op.add_column(
            sa.Column(
                "visual_type",
                sa.String(length=64),
                nullable=False,
                server_default="stylized_human",
            )
        )
        batch_op.create_index(
            "ix_outline_character_visual_type", ["visual_type"], unique=False
        )

    with op.batch_alter_table("comic_image") as batch_op:
        batch_op.add_column(
            sa.Column("artifact_index", sa.Integer(), nullable=False, server_default="1")
        )

    with op.batch_alter_table("generation_task") as batch_op:
        batch_op.add_column(sa.Column("script_task_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("tool_preset_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("parent_task_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "task_kind",
                sa.String(length=64),
                nullable=False,
                server_default="legacy",
            )
        )
        batch_op.add_column(sa.Column("generation_mode", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("seed_strategy", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.create_foreign_key(
            "fk_generation_task_script_task",
            "script_generation_task",
            ["script_task_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_generation_task_tool_preset",
            "image_generation_tool_preset",
            ["tool_preset_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_generation_task_parent",
            "generation_task",
            ["parent_task_id"],
            ["id"],
        )
        for column in (
            "script_task_id",
            "tool_preset_id",
            "parent_task_id",
            "task_kind",
            "generation_mode",
        ):
            batch_op.create_index(f"ix_generation_task_{column}", [column], unique=False)

    with op.batch_alter_table("generation_run") as batch_op:
        batch_op.add_column(sa.Column("batch_task_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_generation_run_batch_task",
            "generation_task",
            ["batch_task_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_generation_run_batch_task_id", ["batch_task_id"], unique=False
        )

    op.create_table(
        "consistency_evaluation_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cids_cross_min", sa.Float(), nullable=False),
        sa.Column("cids_self_min", sa.Float(), nullable=False),
        sa.Column("csd_cross_min", sa.Float(), nullable=False),
        sa.Column("csd_self_min", sa.Float(), nullable=False),
        sa.Column("occm_min", sa.Float(), nullable=False),
        sa.Column("copy_paste_max", sa.Float(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_table(
        "consistency_evaluation_task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_task_id", sa.Integer(), sa.ForeignKey("generation_task.id"), nullable=False),
        sa.Column("script_task_id", sa.Integer(), sa.ForeignKey("script_generation_task.id"), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("thresholds_json", sa.Text(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("metric_version", sa.String(length=64), nullable=False),
        sa.Column("progress_json", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("heartbeat_at", TS, nullable=True),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.UniqueConstraint(
            "batch_task_id",
            "source_hash",
            "metric_version",
            name="uq_consistency_evaluation_task_snapshot",
        ),
    )
    for column in ("batch_task_id", "script_task_id", "status", "source_hash"):
        op.create_index(
            f"ix_consistency_evaluation_task_{column}",
            "consistency_evaluation_task",
            [column],
        )
    op.create_table(
        "consistency_evaluation_track",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "evaluation_task_id",
            sa.Integer(),
            sa.ForeignKey("consistency_evaluation_task.id"),
            nullable=False,
        ),
        sa.Column("candidate_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("image_ids_json", sa.Text(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("adopted_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.UniqueConstraint(
            "evaluation_task_id",
            "candidate_index",
            name="uq_consistency_evaluation_track_candidate",
        ),
    )
    for column in ("evaluation_task_id", "status"):
        op.create_index(
            f"ix_consistency_evaluation_track_{column}",
            "consistency_evaluation_track",
            [column],
        )


def downgrade() -> None:
    op.drop_table("consistency_evaluation_track")
    op.drop_table("consistency_evaluation_task")
    op.drop_table("consistency_evaluation_config")
    with op.batch_alter_table("generation_run") as batch_op:
        batch_op.drop_column("batch_task_id")
    with op.batch_alter_table("generation_task") as batch_op:
        for column in (
            "candidate_count",
            "seed_strategy",
            "generation_mode",
            "task_kind",
            "parent_task_id",
            "tool_preset_id",
            "script_task_id",
        ):
            batch_op.drop_column(column)
    with op.batch_alter_table("comic_image") as batch_op:
        batch_op.drop_column("artifact_index")
    with op.batch_alter_table("outline_character") as batch_op:
        batch_op.drop_column("visual_type")
