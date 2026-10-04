"""移除角色和场景中退役的视觉锚点字段，其余设定及历史任务保持不变。"""

from alembic import op
import sqlalchemy as sa


revision = "0008_remove_visual_anchors"
down_revision = "0007_reference_image_catalog"
branch_labels = None
depends_on = None

TABLES = ("outline_character", "script_character", "script_scene")


def upgrade() -> None:
    """直接删除无关联列，避免 SQLite 重建表影响页面和素材的外键。"""
    for table in TABLES:
        op.drop_column(table, "visual_anchors")


def downgrade() -> None:
    """恢复旧结构；已移除字段用空值填充，不从其他描述推断锚点。"""
    for table in TABLES:
        op.add_column(table, sa.Column("visual_anchors", sa.Text(), nullable=False, server_default=""))
