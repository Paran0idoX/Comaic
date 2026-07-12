"""视觉状态、双模型 ImageSpec、能力绑定与 GenerationRun。"""

from datetime import datetime, timezone
import json

from alembic import op
import sqlalchemy as sa


revision = "0002_visual_consistency_p0"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


TS = sa.String(length=40)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    ]


def _create_model_and_visual_bible_tables() -> None:
    op.create_table(
        "model_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("family", sa.String(length=64), nullable=False),
        sa.Column("variant", sa.String(length=255), nullable=False),
        sa.Column("checkpoint_name", sa.String(length=1024), nullable=False),
        sa.Column("checkpoint_hash", sa.String(length=128), nullable=True),
        sa.Column("component_manifest_json", sa.Text(), nullable=False),
        sa.Column("compiler_key", sa.String(length=120), nullable=False),
        sa.Column("compiler_version", sa.String(length=64), nullable=False),
        sa.Column("default_render_json", sa.Text(), nullable=False),
        sa.Column("license", sa.String(length=255), nullable=True),
        sa.Column("commercial_use_allowed", sa.Boolean(), nullable=True),
        sa.Column("paid_service_allowed", sa.Boolean(), nullable=True),
        sa.Column("fine_tuning_allowed", sa.Boolean(), nullable=True),
        sa.Column("redistribution_allowed", sa.Boolean(), nullable=True),
        sa.Column("license_notice", sa.Text(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_model_profile_family", "model_profile", ["family"])
    op.create_index("ix_model_profile_is_enabled", "model_profile", ["is_enabled"])

    with op.batch_alter_table("image_generation_tool_preset") as batch_op:
        batch_op.add_column(sa.Column("model_profile_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "capabilities_json",
                sa.Text(),
                nullable=False,
                server_default='{"features":["txt2img"],"limits":{}}',
            )
        )
        batch_op.add_column(
            sa.Column(
                "bindings_json",
                sa.Text(),
                nullable=False,
                server_default='{"schema_version":1,"bindings":[]}',
            )
        )
        batch_op.add_column(
            sa.Column("runtime_manifest_json", sa.Text(), nullable=False, server_default="{}")
        )
        batch_op.create_foreign_key(
            "fk_image_tool_model_profile", "model_profile", ["model_profile_id"], ["id"]
        )
        batch_op.create_index(
            "ix_image_generation_tool_preset_model_profile_id", ["model_profile_id"]
        )

    op.create_table(
        "outfit_variant",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("comic_project.id"), nullable=False),
        sa.Column(
            "outline_character_id",
            sa.Integer(),
            sa.ForeignKey("outline_character.id"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("garment_components_json", sa.Text(), nullable=False),
        sa.Column("layer_order_json", sa.Text(), nullable=False),
        sa.Column("colors_json", sa.Text(), nullable=False),
        sa.Column("materials_json", sa.Text(), nullable=False),
        sa.Column("patterns_json", sa.Text(), nullable=False),
        sa.Column("accessories_json", sa.Text(), nullable=False),
        sa.Column("trigger_tokens_json", sa.Text(), nullable=False),
        sa.Column("negative_constraints", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("approved_at", TS, nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "outline_character_id",
            "key",
            "version",
            name="uq_outfit_variant_character_key_version",
        ),
    )
    op.create_index("ix_outfit_variant_project_id", "outfit_variant", ["project_id"])
    op.create_index(
        "ix_outfit_variant_outline_character_id", "outfit_variant", ["outline_character_id"]
    )
    op.create_index("ix_outfit_variant_key", "outfit_variant", ["key"])
    op.create_index("ix_outfit_variant_status", "outfit_variant", ["status"])

    op.create_table(
        "style_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("comic_project.id"), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("model_family", sa.String(length=64), nullable=False),
        sa.Column("positive_tokens", sa.Text(), nullable=False),
        sa.Column("negative_tokens", sa.Text(), nullable=False),
        sa.Column("color_palette_json", sa.Text(), nullable=False),
        sa.Column("lighting", sa.Text(), nullable=False),
        sa.Column("render_defaults_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("approved_at", TS, nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("project_id", "key", "version", name="uq_style_project_key_version"),
    )
    op.create_index("ix_style_profile_project_id", "style_profile", ["project_id"])
    op.create_index("ix_style_profile_key", "style_profile", ["key"])
    op.create_index("ix_style_profile_status", "style_profile", ["status"])

    op.create_table(
        "scene_visual_version",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("comic_project.id"), nullable=False),
        sa.Column("script_scene_id", sa.Integer(), sa.ForeignKey("script_scene.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("landmarks_json", sa.Text(), nullable=False),
        sa.Column("spatial_relations_json", sa.Text(), nullable=False),
        sa.Column("camera_presets_json", sa.Text(), nullable=False),
        sa.Column("object_states_json", sa.Text(), nullable=False),
        sa.Column("color_palette_json", sa.Text(), nullable=False),
        sa.Column("lighting_state_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("approved_at", TS, nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("script_scene_id", "version", name="uq_scene_visual_version"),
    )
    op.create_index("ix_scene_visual_version_project_id", "scene_visual_version", ["project_id"])
    op.create_index(
        "ix_scene_visual_version_script_scene_id", "scene_visual_version", ["script_scene_id"]
    )
    op.create_index("ix_scene_visual_version_status", "scene_visual_version", ["status"])

    with op.batch_alter_table("script_scene") as batch_op:
        batch_op.add_column(sa.Column("selected_visual_version_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_script_scene_selected_visual_version",
            "scene_visual_version",
            ["selected_visual_version_id"],
            ["id"],
        )
    with op.batch_alter_table("script_character") as batch_op:
        batch_op.add_column(sa.Column("outfit_variant_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_script_character_outfit_variant",
            "outfit_variant",
            ["outfit_variant_id"],
            ["id"],
        )
        batch_op.create_index("ix_script_character_outfit_variant_id", ["outfit_variant_id"])

    op.create_table(
        "visual_asset",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("comic_project.id"), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("entity_key", sa.String(length=120), nullable=True),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("model_family", sa.String(length=64), nullable=False),
        sa.Column("storage_kind", sa.String(length=64), nullable=False),
        sa.Column("local_path", sa.Text(), nullable=True),
        sa.Column("renderer_locator", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.String(length=120), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_image_id", sa.Integer(), sa.ForeignKey("comic_image.id"), nullable=True),
        sa.Column("derived_from_asset_id", sa.Integer(), sa.ForeignKey("visual_asset.id"), nullable=True),
        sa.Column("crop_metadata_json", sa.Text(), nullable=False),
        sa.Column("mask_asset_id", sa.Integer(), sa.ForeignKey("visual_asset.id"), nullable=True),
        sa.Column("approved_at", TS, nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "project_id",
            "entity_type",
            "entity_id",
            "entity_key",
            "role",
            "version",
            name="uq_visual_asset_owner_role_version",
        ),
    )
    for name in ("project_id", "entity_type", "entity_id", "entity_key", "role", "sha256", "status"):
        op.create_index(f"ix_visual_asset_{name}", "visual_asset", [name])


def _create_compilation_and_run_tables() -> None:
    op.create_table(
        "continuity_compilation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "script_task_id",
            sa.Integer(),
            sa.ForeignKey("script_generation_task.id"),
            nullable=False,
        ),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("llm_config_id", sa.Integer(), sa.ForeignKey("llm_config.id"), nullable=True),
        sa.Column("llm_model", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("reducer_version", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_continuity_compilation_script_task_id", "continuity_compilation", ["script_task_id"])
    op.create_index("ix_continuity_compilation_source_hash", "continuity_compilation", ["source_hash"])
    op.create_index("ix_continuity_compilation_status", "continuity_compilation", ["status"])

    op.create_table(
        "continuity_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "compilation_id",
            sa.Integer(),
            sa.ForeignKey("continuity_compilation.id"),
            nullable=False,
        ),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("comic_page.id"), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_key", sa.String(length=120), nullable=False),
        sa.Column("timing", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint(
            "compilation_id",
            "page_id",
            "sequence_no",
            name="uq_continuity_event_compilation_page_sequence",
        ),
    )
    op.create_index("ix_continuity_event_compilation_id", "continuity_event", ["compilation_id"])
    op.create_index("ix_continuity_event_page_id", "continuity_event", ["page_id"])
    op.create_index("ix_continuity_event_event_type", "continuity_event", ["event_type"])
    op.create_index("ix_continuity_event_target_key", "continuity_event", ["target_key"])

    op.create_table(
        "visual_state_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "compilation_id",
            sa.Integer(),
            sa.ForeignKey("continuity_compilation.id"),
            nullable=False,
        ),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("comic_page.id"), nullable=False),
        sa.Column(
            "scene_visual_version_id",
            sa.Integer(),
            sa.ForeignKey("scene_visual_version.id"),
            nullable=True,
        ),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("compilation_id", "page_id", name="uq_snapshot_compilation_page"),
    )
    op.create_index("ix_visual_state_snapshot_compilation_id", "visual_state_snapshot", ["compilation_id"])
    op.create_index("ix_visual_state_snapshot_page_id", "visual_state_snapshot", ["page_id"])
    op.create_index("ix_visual_state_snapshot_state_hash", "visual_state_snapshot", ["state_hash"])

    op.create_table(
        "page_shot_plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("comic_page.id"), nullable=False),
        sa.Column(
            "snapshot_id",
            sa.Integer(),
            sa.ForeignKey("visual_state_snapshot.id"),
            nullable=False,
        ),
        sa.Column(
            "planner_preset_id",
            sa.Integer(),
            sa.ForeignKey("image_prompt_preset.id"),
            nullable=True,
        ),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("planner_model", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_page_shot_plan_page_id", "page_shot_plan", ["page_id"])
    op.create_index("ix_page_shot_plan_snapshot_id", "page_shot_plan", ["snapshot_id"])
    op.create_index("ix_page_shot_plan_plan_hash", "page_shot_plan", ["plan_hash"])

    op.create_table(
        "image_spec",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("comic_page.id"), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("visual_state_snapshot.id"), nullable=False),
        sa.Column("shot_plan_id", sa.Integer(), sa.ForeignKey("page_shot_plan.id"), nullable=False),
        sa.Column("model_profile_id", sa.Integer(), sa.ForeignKey("model_profile.id"), nullable=False),
        sa.Column("style_profile_id", sa.Integer(), sa.ForeignKey("style_profile.id"), nullable=True),
        sa.Column(
            "negative_prompt_preset_id",
            sa.Integer(),
            sa.ForeignKey("image_prompt_preset.id"),
            nullable=True,
        ),
        sa.Column("generation_mode", sa.String(length=64), nullable=False),
        sa.Column("spec_json", sa.Text(), nullable=False),
        sa.Column("positive_prompt", sa.Text(), nullable=False),
        sa.Column("negative_prompt", sa.Text(), nullable=False),
        sa.Column("required_capabilities_json", sa.Text(), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("spec_hash", sa.String(length=64), nullable=False),
        sa.Column("compiler_key", sa.String(length=120), nullable=False),
        sa.Column("compiler_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    for name in ("page_id", "snapshot_id", "shot_plan_id", "model_profile_id", "generation_mode", "source_hash", "spec_hash"):
        op.create_index(f"ix_image_spec_{name}", "image_spec", [name])

    op.create_table(
        "generation_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "generation_task_id",
            sa.Integer(),
            sa.ForeignKey("generation_task.id"),
            nullable=False,
        ),
        sa.Column("page_id", sa.Integer(), sa.ForeignKey("comic_page.id"), nullable=False),
        sa.Column("image_spec_id", sa.Integer(), sa.ForeignKey("image_spec.id"), nullable=False),
        sa.Column(
            "tool_preset_id",
            sa.Integer(),
            sa.ForeignKey("image_generation_tool_preset.id"),
            nullable=False,
        ),
        sa.Column("model_profile_id", sa.Integer(), sa.ForeignKey("model_profile.id"), nullable=False),
        sa.Column("candidate_index", sa.Integer(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("seed_applied", sa.Boolean(), nullable=False),
        sa.Column("seed_strategy", sa.String(length=64), nullable=False),
        sa.Column("generation_mode", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("external_request_id", sa.String(length=255), nullable=True),
        sa.Column("workflow_json", sa.Text(), nullable=True),
        sa.Column("workflow_hash", sa.String(length=64), nullable=True),
        sa.Column("bindings_json", sa.Text(), nullable=False),
        sa.Column("model_manifest_json", sa.Text(), nullable=False),
        sa.Column("resolved_assets_json", sa.Text(), nullable=False),
        sa.Column("render_params_json", sa.Text(), nullable=False),
        sa.Column("degradation_json", sa.Text(), nullable=False),
        sa.Column("applied_spec_json", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("finished_at", TS, nullable=True),
        *_timestamps(),
    )
    for name in ("generation_task_id", "page_id", "image_spec_id", "tool_preset_id", "model_profile_id", "status", "external_request_id"):
        op.create_index(f"ix_generation_run_{name}", "generation_run", [name])

    with op.batch_alter_table("comic_image") as batch_op:
        batch_op.add_column(sa.Column("generation_run_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("sha256", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("width", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("height", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_comic_image_generation_run", "generation_run", ["generation_run_id"], ["id"]
        )
        batch_op.create_index("ix_comic_image_generation_run_id", ["generation_run_id"])


def _seed_profiles_and_migrate_legacy_bindings() -> None:
    connection = op.get_bind()
    now = datetime.now(timezone.utc).isoformat()
    profile_table = sa.table(
        "model_profile",
        sa.column("name", sa.String()),
        sa.column("family", sa.String()),
        sa.column("variant", sa.String()),
        sa.column("checkpoint_name", sa.String()),
        sa.column("checkpoint_hash", sa.String()),
        sa.column("component_manifest_json", sa.Text()),
        sa.column("compiler_key", sa.String()),
        sa.column("compiler_version", sa.String()),
        sa.column("default_render_json", sa.Text()),
        sa.column("license", sa.String()),
        sa.column("commercial_use_allowed", sa.Boolean()),
        sa.column("paid_service_allowed", sa.Boolean()),
        sa.column("fine_tuning_allowed", sa.Boolean()),
        sa.column("redistribution_allowed", sa.Boolean()),
        sa.column("license_notice", sa.Text()),
        sa.column("is_enabled", sa.Boolean()),
        sa.column("is_default", sa.Boolean()),
        sa.column("created_at", sa.String()),
        sa.column("updated_at", sa.String()),
    )
    op.bulk_insert(
        profile_table,
        [
            {
                "name": "Anima",
                "family": "anima",
                "variant": "",
                "checkpoint_name": "",
                "checkpoint_hash": None,
                "component_manifest_json": "{}",
                "compiler_key": "anima_v1",
                "compiler_version": "1",
                "default_render_json": json.dumps(
                    {"steps": 28, "cfg": 4.0, "sampler": "euler", "scheduler": "normal"},
                    separators=(",", ":"),
                ),
                "license": None,
                "commercial_use_allowed": None,
                "paid_service_allowed": None,
                "fine_tuning_allowed": None,
                "redistribution_allowed": None,
                "license_notice": None,
                "is_enabled": False,
                "is_default": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "name": "Z-Image",
                "family": "z_image",
                "variant": "",
                "checkpoint_name": "",
                "checkpoint_hash": None,
                "component_manifest_json": "{}",
                "compiler_key": "z_image_v1",
                "compiler_version": "1",
                "default_render_json": json.dumps(
                    {"steps": 36, "cfg": 4.0, "sampler": "euler", "scheduler": "normal"},
                    separators=(",", ":"),
                ),
                "license": "Apache-2.0",
                "commercial_use_allowed": True,
                "paid_service_allowed": True,
                "fine_tuning_allowed": True,
                "redistribution_allowed": True,
                "license_notice": None,
                "is_enabled": False,
                "is_default": True,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )

    rows = connection.execute(
        sa.text(
            "SELECT id, positive_node_id, positive_input_name, negative_node_id, "
            "negative_input_name, seed_node_id, seed_input_name "
            "FROM image_generation_tool_preset"
        )
    ).mappings()
    for row in rows:
        bindings = []
        for source, node_field, input_field in (
            ("prompt.positive", "positive_node_id", "positive_input_name"),
            ("prompt.negative", "negative_node_id", "negative_input_name"),
            ("render.seed", "seed_node_id", "seed_input_name"),
        ):
            if row[node_field] and row[input_field]:
                bindings.append(
                    {
                        "source": source,
                        "node_id": str(row[node_field]),
                        "input_name": str(row[input_field]),
                    }
                )
        connection.execute(
            sa.text(
                "UPDATE image_generation_tool_preset SET capabilities_json=:capabilities, "
                "bindings_json=:bindings WHERE id=:id"
            ),
            {
                "id": row["id"],
                "capabilities": '{"features":["txt2img"],"limits":{}}',
                "bindings": json.dumps(
                    {"schema_version": 1, "bindings": bindings},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        )

    inspector = sa.inspect(connection)
    if "comfy_workflow_preset" in inspector.get_table_names():
        legacy_rows = connection.execute(
            sa.text("SELECT * FROM comfy_workflow_preset ORDER BY id")
        ).mappings()
        for row in legacy_rows:
            exists = connection.execute(
                sa.text(
                    "SELECT 1 FROM image_generation_tool_preset "
                    "WHERE name=:name AND workflow_json=:workflow LIMIT 1"
                ),
                {"name": row["name"], "workflow": row["workflow_json"]},
            ).first()
            if exists:
                continue
            bindings = []
            for source, node_field, input_field in (
                ("prompt.positive", "positive_node_id", "positive_input_name"),
                ("prompt.negative", "negative_node_id", "negative_input_name"),
                ("render.seed", "seed_node_id", "seed_input_name"),
            ):
                if row[node_field] and row[input_field]:
                    bindings.append(
                        {
                            "source": source,
                            "node_id": str(row[node_field]),
                            "input_name": str(row[input_field]),
                        }
                    )
            connection.execute(
                sa.text(
                    "INSERT INTO image_generation_tool_preset "
                    "(name,description,kind,is_default,comfy_base_url,workflow_json,"
                    "positive_node_id,positive_input_name,negative_node_id,negative_input_name,"
                    "seed_node_id,seed_input_name,capabilities_json,bindings_json,"
                    "runtime_manifest_json,created_at,updated_at) VALUES "
                    "(:name,:description,'comfyui',:is_default,NULL,:workflow_json,"
                    ":positive_node_id,:positive_input_name,:negative_node_id,:negative_input_name,"
                    ":seed_node_id,:seed_input_name,:capabilities_json,:bindings_json,'{}',"
                    ":created_at,:updated_at)"
                ),
                {
                    **dict(row),
                    "capabilities_json": '{"features":["txt2img"],"limits":{}}',
                    "bindings_json": json.dumps(
                        {"schema_version": 1, "bindings": bindings},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            )
        op.drop_table("comfy_workflow_preset")


def upgrade() -> None:
    _create_model_and_visual_bible_tables()
    _create_compilation_and_run_tables()
    _seed_profiles_and_migrate_legacy_bindings()


def downgrade() -> None:
    # P0 downgrade 只用于开发；先解除新增外键，再按依赖顺序删除新表。
    with op.batch_alter_table("comic_image") as batch_op:
        batch_op.drop_index("ix_comic_image_generation_run_id")
        batch_op.drop_constraint("fk_comic_image_generation_run", type_="foreignkey")
        batch_op.drop_column("height")
        batch_op.drop_column("width")
        batch_op.drop_column("sha256")
        batch_op.drop_column("generation_run_id")
    for table_name in (
        "generation_run",
        "image_spec",
        "page_shot_plan",
        "visual_state_snapshot",
        "continuity_event",
        "continuity_compilation",
        "visual_asset",
    ):
        op.drop_table(table_name)
    with op.batch_alter_table("script_character") as batch_op:
        batch_op.drop_index("ix_script_character_outfit_variant_id")
        batch_op.drop_constraint("fk_script_character_outfit_variant", type_="foreignkey")
        batch_op.drop_column("outfit_variant_id")
    with op.batch_alter_table("script_scene") as batch_op:
        batch_op.drop_constraint("fk_script_scene_selected_visual_version", type_="foreignkey")
        batch_op.drop_column("selected_visual_version_id")
    op.drop_table("scene_visual_version")
    op.drop_table("style_profile")
    op.drop_table("outfit_variant")
    with op.batch_alter_table("image_generation_tool_preset") as batch_op:
        batch_op.drop_index("ix_image_generation_tool_preset_model_profile_id")
        batch_op.drop_constraint("fk_image_tool_model_profile", type_="foreignkey")
        batch_op.drop_column("runtime_manifest_json")
        batch_op.drop_column("bindings_json")
        batch_op.drop_column("capabilities_json")
        batch_op.drop_column("model_profile_id")
    op.drop_table("model_profile")
