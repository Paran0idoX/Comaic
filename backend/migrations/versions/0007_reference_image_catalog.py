"""参考素材目录、人物五视图和通用任务；保持旧任务及图片地址。"""

from alembic import op
import sqlalchemy as sa


revision = "0007_reference_image_catalog"
down_revision = "0006_character_reference_generation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generation_task", sa.Column("input_snapshot_json", sa.Text(), nullable=True))
    op.create_table(
        "reference_subject",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("comic_project.id"), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("negative_constraints", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("project_id", "entity_type", "key", name="uq_reference_subject_project_type_key"),
    )
    for column in ("project_id", "entity_type", "key"):
        op.create_index(f"ix_reference_subject_{column}", "reference_subject", [column])
    with op.batch_alter_table("script_scene") as batch:
        batch.add_column(sa.Column("reference_subject_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_script_scene_reference_subject", "reference_subject", ["reference_subject_id"], ["id"])
        batch.create_index("ix_script_scene_reference_subject_id", ["reference_subject_id"])
    with op.batch_alter_table("visual_asset") as batch:
        batch.add_column(sa.Column("reference_subject_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("outfit_variant_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_visual_asset_reference_subject", "reference_subject", ["reference_subject_id"], ["id"])
        batch.create_foreign_key("fk_visual_asset_outfit_variant", "outfit_variant", ["outfit_variant_id"], ["id"])
        batch.create_index("ix_visual_asset_reference_subject_id", ["reference_subject_id"])
        batch.create_index("ix_visual_asset_outfit_variant_id", ["outfit_variant_id"])
    with op.batch_alter_table("character_reference_generation_task") as batch:
        batch.alter_column("outline_character_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("entity_type", sa.String(64), nullable=False, server_default="character"))
        batch.add_column(sa.Column("entity_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("entity_key", sa.String(120), nullable=True))
        batch.add_column(sa.Column("reference_subject_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("outfit_variant_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("selected_roles_json", sa.Text(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("source_asset_ids_json", sa.Text(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("subject_snapshot_json", sa.Text(), nullable=False, server_default="{}"))
        batch.create_foreign_key("fk_reference_task_subject", "reference_subject", ["reference_subject_id"], ["id"])
        batch.create_foreign_key("fk_reference_task_outfit", "outfit_variant", ["outfit_variant_id"], ["id"])
        for column in ("entity_type", "reference_subject_id", "outfit_variant_id"):
            batch.create_index(f"ix_character_reference_generation_task_{column}", [column])
    # 冻结旧任务实际三类，新增视角不能改变旧任务完整性和继续生成语义。
    op.execute("UPDATE character_reference_generation_task SET entity_id=outline_character_id, selected_roles_json='[\"identity_face\",\"identity_half_body\",\"identity_full_body\"]'")


def downgrade() -> None:
    # 旧结构无法表达场景/物品归属；拒绝有损降级，保留任务与原图历史。
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM character_reference_generation_task WHERE outline_character_id IS NULL")):
        raise RuntimeError("Cannot downgrade reference catalog with scene/object task history; back up and export it first.")
    if connection.scalar(sa.text("SELECT count(*) FROM reference_subject")):
        raise RuntimeError("Cannot downgrade reference catalog with named subjects; back up and export them first.")
    if connection.scalar(sa.text("SELECT count(*) FROM visual_asset WHERE outfit_variant_id IS NOT NULL OR role IN ('identity_side','identity_back')")):
        raise RuntimeError("Cannot downgrade reference catalog with new asset roles or outfit owners; back up and export them first.")
    if connection.scalar(sa.text("SELECT count(*) FROM character_reference_generation_run WHERE role IN ('identity_side','identity_back')")):
        raise RuntimeError("Cannot downgrade reference catalog with side/back reference task history; back up and export it first.")
    with op.batch_alter_table("character_reference_generation_task") as batch:
        batch.drop_constraint("fk_reference_task_subject", type_="foreignkey")
        batch.drop_constraint("fk_reference_task_outfit", type_="foreignkey")
        for column in ("entity_type", "reference_subject_id", "outfit_variant_id"):
            batch.drop_index(f"ix_character_reference_generation_task_{column}")
        for column in ("entity_type", "entity_id", "entity_key", "reference_subject_id", "outfit_variant_id", "selected_roles_json", "source_asset_ids_json", "subject_snapshot_json"):
            batch.drop_column(column)
        batch.alter_column("outline_character_id", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("visual_asset") as batch:
        batch.drop_index("ix_visual_asset_reference_subject_id")
        batch.drop_index("ix_visual_asset_outfit_variant_id")
        batch.drop_constraint("fk_visual_asset_reference_subject", type_="foreignkey")
        batch.drop_constraint("fk_visual_asset_outfit_variant", type_="foreignkey")
        batch.drop_column("reference_subject_id")
        batch.drop_column("outfit_variant_id")
    with op.batch_alter_table("script_scene") as batch:
        batch.drop_index("ix_script_scene_reference_subject_id")
        batch.drop_constraint("fk_script_scene_reference_subject", type_="foreignkey")
        batch.drop_column("reference_subject_id")
    op.drop_table("reference_subject")
    op.drop_column("generation_task", "input_snapshot_json")
