"""以 Prompt 类型替代具体图片模型配置。"""

from alembic import op
import sqlalchemy as sa


revision = "0003_prompt_types"
down_revision = "0002_visual_consistency_p0"
branch_labels = None
depends_on = None


def _add_and_map_columns() -> None:
    """先添加并回填新列，确保后续重建 SQLite 表时不会丢失语义。"""

    with op.batch_alter_table("image_prompt_preset") as batch_op:
        batch_op.add_column(
            sa.Column("tag_content", sa.Text(), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column(
                "natural_language_content",
                sa.Text(),
                nullable=False,
                server_default="",
            )
        )
    op.execute(
        "UPDATE image_prompt_preset SET tag_content=content, "
        "natural_language_content=content WHERE kind='negative_prompt'"
    )
    op.execute(
        "DELETE FROM image_prompt_preset "
        "WHERE kind='script_to_image_system_prompt'"
    )

    with op.batch_alter_table("image_generation_tool_preset") as batch_op:
        batch_op.add_column(
            sa.Column(
                "provider",
                sa.String(length=64),
                nullable=False,
                server_default="comfyui",
            )
        )
        batch_op.add_column(
            sa.Column(
                "prompt_type",
                sa.String(length=64),
                nullable=False,
                server_default="natural_language",
            )
        )
    op.execute("UPDATE image_generation_tool_preset SET provider=kind")
    op.execute(
        "UPDATE image_generation_tool_preset SET prompt_type=CASE "
        "WHEN (SELECT family FROM model_profile "
        "      WHERE model_profile.id=image_generation_tool_preset.model_profile_id)='anima' "
        "THEN 'tag' "
        "WHEN (SELECT family FROM model_profile "
        "      WHERE model_profile.id=image_generation_tool_preset.model_profile_id)='z_image' "
        "THEN 'natural_language' "
        "ELSE 'natural_language' END"
    )

    with op.batch_alter_table("image_spec") as batch_op:
        batch_op.add_column(
            sa.Column(
                "prompt_type",
                sa.String(length=64),
                nullable=False,
                server_default="natural_language",
            )
        )
    op.execute(
        "UPDATE image_spec SET prompt_type=CASE "
        "WHEN (SELECT family FROM model_profile "
        "      WHERE model_profile.id=image_spec.model_profile_id)='anima' "
        "THEN 'tag' ELSE 'natural_language' END"
    )

    with op.batch_alter_table("generation_run") as batch_op:
        batch_op.add_column(
            sa.Column(
                "provider",
                sa.String(length=64),
                nullable=False,
                server_default="comfyui",
            )
        )
        batch_op.add_column(
            sa.Column(
                "prompt_type",
                sa.String(length=64),
                nullable=False,
                server_default="natural_language",
            )
        )
    op.execute(
        "UPDATE generation_run SET provider=COALESCE("
        "(SELECT kind FROM image_generation_tool_preset "
        " WHERE image_generation_tool_preset.id=generation_run.tool_preset_id), 'comfyui')"
    )
    op.execute(
        "UPDATE generation_run SET prompt_type=COALESCE("
        "(SELECT prompt_type FROM image_spec "
        " WHERE image_spec.id=generation_run.image_spec_id), 'natural_language')"
    )

    with op.batch_alter_table("style_profile") as batch_op:
        for name in (
            "positive_tag",
            "negative_tag",
            "positive_natural_language",
            "negative_natural_language",
        ):
            batch_op.add_column(
                sa.Column(name, sa.Text(), nullable=False, server_default="")
            )
    op.execute(
        "UPDATE style_profile SET positive_tag=positive_tokens, "
        "negative_tag=negative_tokens, "
        "positive_natural_language=positive_tokens, "
        "negative_natural_language=negative_tokens"
    )


def _drop_model_dependent_columns() -> None:
    """SQLite 通过 batch 重建表，移除模型、许可证和运行参数依赖。"""

    with op.batch_alter_table("generation_run", recreate="always") as batch_op:
        batch_op.drop_index("ix_generation_run_model_profile_id")
        batch_op.drop_column("model_profile_id")
        batch_op.drop_column("model_manifest_json")
        batch_op.drop_column("render_params_json")
        batch_op.create_index("ix_generation_run_provider", ["provider"])
        batch_op.create_index("ix_generation_run_prompt_type", ["prompt_type"])

    with op.batch_alter_table("image_spec", recreate="always") as batch_op:
        batch_op.drop_index("ix_image_spec_model_profile_id")
        batch_op.drop_column("model_profile_id")
        batch_op.create_index("ix_image_spec_prompt_type", ["prompt_type"])

    with op.batch_alter_table(
        "image_generation_tool_preset", recreate="always"
    ) as batch_op:
        batch_op.drop_index("ix_image_generation_tool_preset_kind")
        batch_op.drop_index("ix_image_generation_tool_preset_model_profile_id")
        batch_op.drop_constraint("fk_image_tool_model_profile", type_="foreignkey")
        batch_op.drop_column("kind")
        batch_op.drop_column("model_profile_id")
        batch_op.drop_column("runtime_manifest_json")
        batch_op.create_index(
            "ix_image_generation_tool_preset_provider", ["provider"]
        )
        batch_op.create_index(
            "ix_image_generation_tool_preset_prompt_type", ["prompt_type"]
        )

    with op.batch_alter_table("style_profile", recreate="always") as batch_op:
        batch_op.drop_column("model_family")
        batch_op.drop_column("positive_tokens")
        batch_op.drop_column("negative_tokens")
        batch_op.drop_column("render_defaults_json")

    # 历史 LoRA 只归档以保留审计数据；新业务层不再允许创建或重新批准。
    op.execute(
        "UPDATE visual_asset SET status='archived', approved_at=NULL WHERE role='lora'"
    )
    with op.batch_alter_table("visual_asset", recreate="always") as batch_op:
        batch_op.drop_column("model_family")

    # 旧 prompt_ready 只代表单一页面 Prompt 已生成，并不具备新的三类 ImageSpec。
    # 回退到 script_ready，要求用户重新编译后再由 Service 推进到 spec_ready。
    op.execute("UPDATE comic_page SET status='script_ready' WHERE status='prompt_ready'")
    with op.batch_alter_table("comic_page", recreate="always") as batch_op:
        batch_op.drop_column("image_prompt")

    op.drop_table("model_profile")


def upgrade() -> None:
    _add_and_map_columns()
    _drop_model_dependent_columns()


def downgrade() -> None:
    """开发期降级：恢复旧字段，并把 Prompt 类型映射回两个兼容档案。"""

    op.create_table(
        "model_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("family", sa.String(length=64), nullable=False),
        sa.Column("variant", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("checkpoint_name", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("checkpoint_hash", sa.String(length=128), nullable=True),
        sa.Column("component_manifest_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("compiler_key", sa.String(length=120), nullable=False),
        sa.Column("compiler_version", sa.String(length=64), nullable=False, server_default="1"),
        sa.Column("default_render_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("license", sa.String(length=255), nullable=True),
        sa.Column("commercial_use_allowed", sa.Boolean(), nullable=True),
        sa.Column("paid_service_allowed", sa.Boolean(), nullable=True),
        sa.Column("fine_tuning_allowed", sa.Boolean(), nullable=True),
        sa.Column("redistribution_allowed", sa.Boolean(), nullable=True),
        sa.Column("license_notice", sa.Text(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(length=40), nullable=False, server_default=""),
    )
    op.execute(
        "INSERT INTO model_profile "
        "(id,name,family,compiler_key,created_at,updated_at) VALUES "
        "(1,'Tag compatibility','anima','anima_v1','',''),"
        "(2,'Natural language compatibility','z_image','z_image_v1','','')"
    )
    op.create_index("ix_model_profile_family", "model_profile", ["family"])
    op.create_index("ix_model_profile_is_enabled", "model_profile", ["is_enabled"])

    with op.batch_alter_table("comic_page", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("image_prompt", sa.Text(), nullable=True))
    op.execute("UPDATE comic_page SET status='prompt_ready' WHERE status='spec_ready'")

    with op.batch_alter_table("visual_asset", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column("model_family", sa.String(length=64), nullable=False, server_default="generic")
        )
    with op.batch_alter_table("style_profile", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column("model_family", sa.String(length=64), nullable=False, server_default="generic")
        )
        batch_op.add_column(sa.Column("positive_tokens", sa.Text(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("negative_tokens", sa.Text(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("render_defaults_json", sa.Text(), nullable=False, server_default="{}"))
    op.execute(
        "UPDATE style_profile SET positive_tokens=positive_tag, negative_tokens=negative_tag"
    )

    with op.batch_alter_table("image_generation_tool_preset", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("kind", sa.String(length=64), nullable=False, server_default="comfyui"))
        batch_op.add_column(sa.Column("model_profile_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("runtime_manifest_json", sa.Text(), nullable=False, server_default="{}"))
    op.execute("UPDATE image_generation_tool_preset SET kind=provider")
    op.execute(
        "UPDATE image_generation_tool_preset SET model_profile_id="
        "CASE WHEN prompt_type='tag' THEN 1 ELSE 2 END"
    )

    with op.batch_alter_table("image_spec", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("model_profile_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE image_spec SET model_profile_id=CASE WHEN prompt_type='tag' THEN 1 ELSE 2 END"
    )
    with op.batch_alter_table("generation_run", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("model_profile_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("model_manifest_json", sa.Text(), nullable=False, server_default="{}"))
        batch_op.add_column(sa.Column("render_params_json", sa.Text(), nullable=False, server_default="{}"))
    op.execute(
        "UPDATE generation_run SET model_profile_id=CASE WHEN prompt_type='tag' THEN 1 ELSE 2 END"
    )

    for table_name, columns in (
        ("generation_run", ("provider", "prompt_type")),
        ("image_spec", ("prompt_type",)),
        ("image_generation_tool_preset", ("provider", "prompt_type")),
        (
            "style_profile",
            (
                "positive_tag",
                "negative_tag",
                "positive_natural_language",
                "negative_natural_language",
            ),
        ),
        ("image_prompt_preset", ("tag_content", "natural_language_content")),
    ):
        with op.batch_alter_table(table_name, recreate="always") as batch_op:
            for column in columns:
                batch_op.drop_column(column)
