"""P0 重构前的 Comaic 数据库基线。"""

from alembic import op
import sqlalchemy as sa


revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


TS = sa.String(length=40)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "comic_project",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "image_prompt_preset",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_image_prompt_preset_kind", "image_prompt_preset", ["kind"])
    op.create_table(
        "comfy_workflow_preset",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("workflow_json", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("positive_node_id", sa.String(length=255), nullable=False),
        sa.Column("positive_input_name", sa.String(length=255), nullable=False),
        sa.Column("negative_node_id", sa.String(length=255), nullable=True),
        sa.Column("negative_input_name", sa.String(length=255), nullable=True),
        sa.Column("seed_node_id", sa.String(length=255), nullable=True),
        sa.Column("seed_input_name", sa.String(length=255), nullable=True),
        *_timestamps(),
    )
    op.create_table(
        "image_generation_tool_preset",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("comfy_base_url", sa.String(length=1024), nullable=True),
        sa.Column("workflow_json", sa.Text(), nullable=True),
        sa.Column("positive_node_id", sa.String(length=255), nullable=True),
        sa.Column("positive_input_name", sa.String(length=255), nullable=True),
        sa.Column("negative_node_id", sa.String(length=255), nullable=True),
        sa.Column("negative_input_name", sa.String(length=255), nullable=True),
        sa.Column("seed_node_id", sa.String(length=255), nullable=True),
        sa.Column("seed_input_name", sa.String(length=255), nullable=True),
        sa.Column("api_base_url", sa.String(length=1024), nullable=True),
        sa.Column("endpoint_path", sa.String(length=255), nullable=True),
        sa.Column("api_key", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("size", sa.String(length=64), nullable=True),
        sa.Column("response_format", sa.String(length=64), nullable=True),
        sa.Column("seed_field_name", sa.String(length=255), nullable=True),
        sa.Column("negative_prompt_field_name", sa.String(length=255), nullable=True),
        sa.Column("extra_body_json", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index(
        "ix_image_generation_tool_preset_kind", "image_generation_tool_preset", ["kind"]
    )
    op.create_table(
        "llm_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("base_url", sa.String(length=1024), nullable=False),
        sa.Column("model_names", sa.Text(), nullable=False),
        sa.Column("default_model", sa.String(length=255), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_llm_config_is_active", "llm_config", ["is_active"])
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("script_section_max_concurrency", sa.Integer(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "session",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("comic_project.id"), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("thread_id"),
    )
    op.create_index("ix_session_project_id", "session", ["project_id"])
    op.create_index("ix_session_thread_id", "session", ["thread_id"], unique=True)
    op.create_table(
        "outline_version",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("comic_project.id"), nullable=False),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("session.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("confirmed_at", TS, nullable=True),
    )
    op.create_index("ix_outline_version_project_id", "outline_version", ["project_id"])
    op.create_index("ix_outline_version_session_id", "outline_version", ["session_id"])
    op.create_table(
        "outline_character",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("outline_version_id", sa.Integer(), sa.ForeignKey("outline_version.id"), nullable=False),
        sa.Column("character_key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=255), nullable=False),
        sa.Column("background", sa.Text(), nullable=False),
        sa.Column("appearance", sa.Text(), nullable=False),
        sa.Column("visual_anchors", sa.Text(), nullable=False),
        sa.Column("negative_constraints", sa.Text(), nullable=False),
        sa.Column("default_hairstyle", sa.Text(), nullable=False),
        sa.Column("default_clothing", sa.Text(), nullable=False),
        sa.Column("default_accessories", sa.Text(), nullable=False),
        sa.Column("default_color_palette", sa.Text(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "outline_version_id", "character_key", name="uq_outline_character_version_key"
        ),
    )
    op.create_index("ix_outline_character_outline_version_id", "outline_character", ["outline_version_id"])
    op.create_index("ix_outline_character_character_key", "outline_character", ["character_key"])
    op.create_table(
        "script_generation_task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("comic_project.id"), nullable=False),
        sa.Column("outline_version_id", sa.Integer(), sa.ForeignKey("outline_version.id"), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=64), nullable=False),
        sa.Column("total_pages", sa.Integer(), nullable=False),
        sa.Column("target_page_no", sa.Integer(), nullable=True),
        sa.Column("user_requirement", sa.Text(), nullable=True),
        sa.Column("section_plan", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("heartbeat_at", TS, nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_script_generation_task_project_id", "script_generation_task", ["project_id"])
    op.create_table(
        "script_section",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("script_generation_task.id"), nullable=False),
        sa.Column("section_no", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_script_section_task_id", "script_section", ["task_id"])
    op.create_table(
        "script_scene",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("script_generation_task.id"), nullable=False),
        sa.Column("scene_key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("location_type", sa.String(length=255), nullable=False),
        sa.Column("time_of_day", sa.String(length=255), nullable=False),
        sa.Column("lighting", sa.Text(), nullable=False),
        sa.Column("weather", sa.String(length=255), nullable=False),
        sa.Column("environment_details", sa.Text(), nullable=False),
        sa.Column("color_palette", sa.Text(), nullable=False),
        sa.Column("visual_anchors", sa.Text(), nullable=False),
        sa.Column("negative_constraints", sa.Text(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("task_id", "scene_key", name="uq_script_scene_task_key"),
    )
    op.create_index("ix_script_scene_task_id", "script_scene", ["task_id"])
    op.create_index("ix_script_scene_scene_key", "script_scene", ["scene_key"])
    op.create_table(
        "script_character",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("script_section.id"), nullable=False),
        sa.Column("outline_character_id", sa.Integer(), sa.ForeignKey("outline_character.id"), nullable=True),
        sa.Column("character_key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("section_role", sa.String(length=255), nullable=False),
        sa.Column("current_hairstyle", sa.Text(), nullable=False),
        sa.Column("current_clothing", sa.Text(), nullable=False),
        sa.Column("current_accessories", sa.Text(), nullable=False),
        sa.Column("current_state", sa.Text(), nullable=False),
        sa.Column("emotion", sa.Text(), nullable=False),
        sa.Column("temporary_changes", sa.Text(), nullable=False),
        sa.Column("visual_anchors", sa.Text(), nullable=False),
        sa.Column("negative_constraints", sa.Text(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("section_id", "character_key", name="uq_script_character_section_key"),
    )
    op.create_index("ix_script_character_section_id", "script_character", ["section_id"])
    op.create_index("ix_script_character_outline_character_id", "script_character", ["outline_character_id"])
    op.create_index("ix_script_character_character_key", "script_character", ["character_key"])
    op.create_table(
        "comic_page",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("comic_project.id"), nullable=False),
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("script_section.id"), nullable=True),
        sa.Column("scene_id", sa.Integer(), sa.ForeignKey("script_scene.id"), nullable=True),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("characters", sa.Text(), nullable=True),
        sa.Column("clothing", sa.Text(), nullable=True),
        sa.Column("scene", sa.Text(), nullable=True),
        sa.Column("composition", sa.Text(), nullable=True),
        sa.Column("character_action", sa.Text(), nullable=True),
        sa.Column("dialogue", sa.Text(), nullable=True),
        sa.Column("image_prompt", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("script_review_status", sa.String(length=64), nullable=False),
        sa.Column("script_review_error", sa.Text(), nullable=True),
        sa.Column("selected_image_id", sa.Integer(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_comic_page_project_id", "comic_page", ["project_id"])
    op.create_index("ix_comic_page_section_id", "comic_page", ["section_id"])
    op.create_index("ix_comic_page_scene_id", "comic_page", ["scene_id"])
    op.create_table(
        "comic_image",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("comic_page.id"), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("local_path", sa.Text(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("workflow_name", sa.String(length=255), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("negative_prompt", sa.Text(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("is_selected", sa.Boolean(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_comic_image_page_id", "comic_image", ["page_id"])
    with op.batch_alter_table("comic_page") as batch_op:
        batch_op.create_foreign_key(
            "fk_comic_page_selected_image_id", "comic_image", ["selected_image_id"], ["id"]
        )
    op.create_table(
        "comic_page_character",
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("comic_page.id"), primary_key=True),
        sa.Column("character_id", sa.Integer(), sa.ForeignKey("script_character.id"), primary_key=True),
    )
    op.create_table(
        "generation_task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("comic_project.id"), nullable=False),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("comic_page.id"), nullable=True),
        sa.Column("comfy_prompt_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("batch_size", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("heartbeat_at", TS, nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_generation_task_project_id", "generation_task", ["project_id"])


def downgrade() -> None:
    for table_name in (
        "generation_task",
        "comic_page_character",
        "comic_image",
        "comic_page",
        "script_character",
        "script_scene",
        "script_section",
        "script_generation_task",
        "outline_character",
        "outline_version",
        "session",
        "app_settings",
        "llm_config",
        "image_generation_tool_preset",
        "comfy_workflow_preset",
        "image_prompt_preset",
        "comic_project",
    ):
        op.drop_table(table_name)
