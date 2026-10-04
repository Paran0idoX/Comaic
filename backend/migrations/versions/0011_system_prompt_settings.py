"""保存模型级全局提示词和任务提示词覆盖，保留 Markdown 默认值。"""

from alembic import op
import sqlalchemy as sa
import json

revision = "0011_system_prompt_settings"
down_revision = "0010_page_scene_conditions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("llm_config", sa.Column("model_system_prompts_json", sa.Text(), nullable=True))
    op.add_column("llm_config", sa.Column("model_system_prompt_defaults_json", sa.Text(), nullable=True))
    op.add_column("app_settings", sa.Column("system_prompts_json", sa.Text(), nullable=True))
    # 为已有 DeepSeek 配置保留默认文件关联；通用请求注入层不再识别 Provider。
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, model_names FROM llm_config WHERE provider='deepseek'"))
    for config_id, model_names in rows:
        defaults = {model: ["deepseek_infinite_gen_4_1_flash.md", "deepseek_creative_system_prompt.md"]
                    for model in json.loads(model_names or "[]")}
        connection.execute(sa.text("UPDATE llm_config SET model_system_prompt_defaults_json=:defaults WHERE id=:id"),
                           {"defaults": json.dumps(defaults), "id": config_id})


def downgrade():
    with op.batch_alter_table("app_settings") as batch:
        batch.drop_column("system_prompts_json")
    with op.batch_alter_table("llm_config") as batch:
        batch.drop_column("model_system_prompt_defaults_json")
        batch.drop_column("model_system_prompts_json")
