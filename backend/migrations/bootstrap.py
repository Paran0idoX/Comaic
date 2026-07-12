from datetime import datetime
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import make_url

from backend.models.database import DATABASE_URL, engine


BASELINE_REVISION = "0001_baseline"
REQUIRED_BASELINE_COLUMNS = {
    "app_settings": {"id", "script_section_max_concurrency", "created_at", "updated_at"},
    "comfy_workflow_preset": {
        "id", "name", "description", "workflow_json", "is_default",
        "positive_node_id", "positive_input_name", "negative_node_id",
        "negative_input_name", "seed_node_id", "seed_input_name", "created_at", "updated_at",
    },
    "comic_image": {
        "id", "page_id", "image_url", "local_path", "seed", "workflow_name", "prompt",
        "negative_prompt", "score", "is_selected", "created_at",
    },
    "comic_page": {
        "id", "project_id", "section_id", "scene_id", "page_no", "summary", "characters",
        "clothing", "scene", "composition", "character_action", "dialogue", "image_prompt",
        "status", "script_review_status", "script_review_error", "selected_image_id",
        "created_at", "updated_at",
    },
    "comic_page_character": {"page_id", "character_id"},
    "comic_project": {"id", "title", "created_at", "updated_at"},
    "generation_task": {
        "id", "project_id", "page_id", "comfy_prompt_id", "status", "batch_size",
        "error_message", "heartbeat_at", "created_at", "updated_at",
    },
    "image_generation_tool_preset": {
        "id", "name", "description", "kind", "is_default", "comfy_base_url", "workflow_json",
        "positive_node_id", "positive_input_name", "negative_node_id", "negative_input_name",
        "seed_node_id", "seed_input_name", "api_base_url", "endpoint_path", "api_key", "model",
        "size", "response_format", "seed_field_name", "negative_prompt_field_name",
        "extra_body_json", "created_at", "updated_at",
    },
    "image_prompt_preset": {
        "id", "name", "description", "kind", "content", "is_default", "created_at", "updated_at",
    },
    "llm_config": {
        "id", "name", "provider", "base_url", "model_names", "default_model", "api_key",
        "is_active", "created_at", "updated_at",
    },
    "outline_character": {
        "id", "outline_version_id", "character_key", "name", "role", "background", "appearance",
        "visual_anchors", "negative_constraints", "default_hairstyle", "default_clothing",
        "default_accessories", "default_color_palette", "created_at", "updated_at",
    },
    "outline_version": {
        "id", "project_id", "session_id", "version_no", "content", "status", "created_at",
        "confirmed_at",
    },
    "script_character": {
        "id", "section_id", "outline_character_id", "character_key", "name", "section_role",
        "current_hairstyle", "current_clothing", "current_accessories", "current_state", "emotion",
        "temporary_changes", "visual_anchors", "negative_constraints", "created_at", "updated_at",
    },
    "script_generation_task": {
        "id", "project_id", "outline_version_id", "status", "mode", "total_pages",
        "target_page_no", "user_requirement", "section_plan", "error_message", "heartbeat_at",
        "created_at", "updated_at",
    },
    "script_scene": {
        "id", "task_id", "scene_key", "name", "location_type", "time_of_day", "lighting",
        "weather", "environment_details", "color_palette", "visual_anchors", "negative_constraints",
        "created_at", "updated_at",
    },
    "script_section": {
        "id", "task_id", "section_no", "page_start", "page_end", "title", "description",
        "status", "error_message", "created_at", "updated_at",
    },
    "session": {"id", "project_id", "thread_id", "purpose", "created_at", "updated_at"},
}


def _alembic_config() -> Config:
    """创建指向项目迁移目录的 Alembic 配置。"""

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend" / "migrations"))
    config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))
    return config


def _validate_unversioned_schema() -> None:
    """只接受当前 P0 前基线，避免把未知旧结构误标成 baseline。"""

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    missing_tables = set(REQUIRED_BASELINE_COLUMNS) - table_names
    unexpected_tables = table_names - set(REQUIRED_BASELINE_COLUMNS)
    if missing_tables or unexpected_tables:
        raise RuntimeError(
            "Unversioned database does not match the supported baseline; "
            f"missing tables: {sorted(missing_tables)}, "
            f"unexpected tables: {sorted(unexpected_tables)}"
        )
    for table_name, expected_columns in REQUIRED_BASELINE_COLUMNS.items():
        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        missing_columns = expected_columns - actual_columns
        unexpected_columns = actual_columns - expected_columns
        if missing_columns or unexpected_columns:
            raise RuntimeError(
                "Unversioned database does not match the supported baseline; "
                f"{table_name} missing columns: {sorted(missing_columns)}, "
                f"unexpected columns: {sorted(unexpected_columns)}"
            )


def _backup_sqlite_database() -> Path | None:
    """迁移未纳管的 SQLite 前生成一次旁路备份；其它数据库不做隐式复制。"""

    url = make_url(DATABASE_URL)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    source = Path(url.database)
    if not source.is_absolute():
        source = Path.cwd() / source
    if not source.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    destination = source.with_suffix(f"{source.suffix}.pre-alembic-{timestamp}.bak")
    # SQLite backup API 会把 WAL 中已提交页面一并复制，避免直接 copy 数据库文件得到不完整快照。
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as source_connection:
        with sqlite3.connect(destination) as destination_connection:
            source_connection.backup(destination_connection)
    return destination


def upgrade_database() -> None:
    """把新库或受支持的未纳管 SQLite 安全升级到 Alembic head。"""

    config = _alembic_config()
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if table_names and "alembic_version" not in table_names:
        _validate_unversioned_schema()
        _backup_sqlite_database()
        command.stamp(config, BASELINE_REVISION)
    command.upgrade(config, "head")
