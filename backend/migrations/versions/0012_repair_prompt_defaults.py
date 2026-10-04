"""修复已执行早期 0011 的数据库，避免修改旧迁移后 Alembic 跳过新增字段。"""

import json

from alembic import op
import sqlalchemy as sa

revision = "0012_repair_prompt_defaults"
down_revision = "0011_system_prompt_settings"
branch_labels = None
depends_on = None


def upgrade():
    """完整 0011 无需处理；早期 0011 只补缺列并初始化默认模板关联。"""
    connection = op.get_bind()
    columns = {column["name"] for column in sa.inspect(connection).get_columns("llm_config")}
    if "model_system_prompt_defaults_json" in columns:
        return
    op.add_column(
        "llm_config",
        sa.Column("model_system_prompt_defaults_json", sa.Text(), nullable=True),
    )
    rows = connection.execute(sa.text(
        "SELECT id, model_names FROM llm_config WHERE provider='deepseek'"
    )).fetchall()
    for config_id, model_names in rows:
        defaults = {
            model: ["deepseek_infinite_gen_4_1_flash.md", "deepseek_creative_system_prompt.md"]
            for model in json.loads(model_names or "[]")
        }
        connection.execute(
            sa.text("UPDATE llm_config SET model_system_prompt_defaults_json=:defaults WHERE id=:id"),
            {"defaults": json.dumps(defaults, ensure_ascii=False), "id": config_id},
        )


def downgrade():
    """该字段也属于完整 0011，回退修复版本时保留，由 0011 的 downgrade 移除。"""
    pass
