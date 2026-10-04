"""分离固定地点与逐页环境；旧场景和冻结输入保持原样。"""

from alembic import op
import sqlalchemy as sa

revision = "0010_page_scene_conditions"
down_revision = "0009_reference_visual_profiles"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("comic_page", sa.Column("scene_conditions_json", sa.Text(), nullable=True))
    for table in ("script_generation_task", "reference_subject"):
        op.add_column(table, sa.Column("scene_definition_version", sa.Integer(), nullable=False, server_default="1"))


def downgrade():
    for table in ("script_generation_task", "reference_subject"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("scene_definition_version")
    with op.batch_alter_table("comic_page") as batch:
        batch.drop_column("scene_conditions_json")
