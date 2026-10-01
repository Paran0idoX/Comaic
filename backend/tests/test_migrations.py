import os
from pathlib import Path
import sqlite3
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def _environment(database: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{database}"
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(ROOT), env.get("PYTHONPATH")) if value
    )
    return env


def _run_python(
    code: str, database: Path, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=_environment(database),
        check=check,
        text=True,
        capture_output=True,
    )


def test_empty_database_upgrades_to_model_independent_head(tmp_path: Path) -> None:
    database = tmp_path / "empty.sqlite3"
    _run_python("from backend.models.database import init_db; init_db()", database)

    with sqlite3.connect(database) as connection:
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
        model_table = connection.execute(
            "SELECT count(1) FROM sqlite_master WHERE type='table' AND name='model_profile'"
        ).fetchone()[0]
        spec_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(image_spec)").fetchall()
        }
        tool_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(image_generation_tool_preset)"
            ).fetchall()
        }
        run_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(generation_run)"
            ).fetchall()
        }
        task_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(generation_task)"
            ).fetchall()
        }
        consistency_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'consistency_%'"
            ).fetchall()
        }
        character_reference_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name LIKE 'character_reference_%'"
            ).fetchall()
        }
    assert revision == "0007_reference_image_catalog"
    assert model_table == 0
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT count(1) FROM sqlite_master "
                "WHERE type='table' AND name='image_spec_compilation'"
            ).fetchone()[0]
            == 1
        )
    assert "prompt_type" in spec_columns
    assert "model_profile_id" not in spec_columns
    assert {"provider", "prompt_type"} <= tool_columns
    assert {"kind", "model_profile_id", "runtime_manifest_json"}.isdisjoint(
        tool_columns
    )
    assert {"workflow_hash", "seed_strategy", "provider", "prompt_type"} <= run_columns
    assert "batch_task_id" in run_columns
    assert {
        "script_task_id",
        "parent_task_id",
        "task_kind",
        "generation_mode",
        "candidate_count",
    } <= task_columns
    assert {
        "consistency_evaluation_config",
        "consistency_evaluation_task",
        "consistency_evaluation_track",
    } <= consistency_tables
    assert {
        "character_reference_generation_task",
        "character_reference_generation_run",
        "character_reference_image",
    } <= character_reference_tables
    assert {"model_profile_id", "model_manifest_json", "render_params_json"}.isdisjoint(
        run_columns
    )
    _run_python(
        "from alembic import command; from alembic.config import Config; "
        "command.check(Config('alembic.ini'))",
        database,
    )


def test_unversioned_baseline_is_backed_up_and_preserves_data(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    _run_python(
        "from alembic import command; from alembic.config import Config; "
        "command.upgrade(Config('alembic.ini'), '0001_baseline')",
        database,
    )
    timestamp = "2026-01-01T00:00:00+00:00"
    workflow = '{"1":{"inputs":{"text":"legacy","seed":1}}}'
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO comic_project (id,title,created_at,updated_at) VALUES (1,?,?,?)",
            ("Legacy project", timestamp, timestamp),
        )
        connection.execute(
            "INSERT INTO script_generation_task "
            "(id,project_id,outline_version_id,status,mode,total_pages,target_page_no,"
            "user_requirement,section_plan,error_message,heartbeat_at,created_at,updated_at) "
            "VALUES (1,1,NULL,'succeeded','batch',1,NULL,NULL,NULL,NULL,NULL,?,?)",
            (timestamp, timestamp),
        )
        connection.execute(
            "INSERT INTO script_section "
            "(id,task_id,section_no,page_start,page_end,title,description,status,error_message,created_at,updated_at) "
            "VALUES (1,1,1,1,1,'Opening','Legacy section','completed',NULL,?,?)",
            (timestamp, timestamp),
        )
        connection.execute(
            "INSERT INTO script_scene "
            "(id,task_id,scene_key,name,location_type,time_of_day,lighting,weather,"
            "environment_details,color_palette,visual_anchors,negative_constraints,created_at,updated_at) "
            "VALUES (1,1,'room','Room','interior','night','lamp','clear','old room',"
            "'blue','round window','no text',?,?)",
            (timestamp, timestamp),
        )
        connection.execute(
            "INSERT INTO comic_page "
            "(id,project_id,section_id,scene_id,page_no,summary,characters,clothing,scene,"
            "composition,character_action,dialogue,image_prompt,status,script_review_status,"
            "script_review_error,selected_image_id,created_at,updated_at) "
            "VALUES (1,1,1,1,1,'summary','Alice','coat','room','wide','stands','none',"
            "'legacy prompt','prompt_ready','passed',NULL,NULL,?,?)",
            (timestamp, timestamp),
        )
        connection.execute(
            "INSERT INTO comic_image "
            "(id,page_id,image_url,local_path,seed,workflow_name,prompt,negative_prompt,score,"
            "is_selected,created_at) VALUES (1,1,NULL,'outputs/legacy.png',42,'Legacy workflow',"
            "'legacy prompt','bad',0.5,1,?)",
            (timestamp,),
        )
        connection.execute("UPDATE comic_page SET selected_image_id=1 WHERE id=1")
        connection.execute(
            "INSERT INTO llm_config "
            "(id,name,provider,base_url,model_names,default_model,api_key,is_active,created_at,updated_at) "
            "VALUES (1,'Local','openai_compatible','http://localhost','[\"model\"]','model',NULL,1,?,?)",
            (timestamp, timestamp),
        )
        connection.execute(
            "INSERT INTO image_generation_tool_preset "
            "(id,name,description,kind,is_default,workflow_json,positive_node_id,"
            "positive_input_name,seed_node_id,seed_input_name,created_at,updated_at) "
            "VALUES (1,'Legacy workflow',NULL,'comfyui',1,?,'1','text','1','seed',?,?)",
            (workflow, timestamp, timestamp),
        )
        connection.execute("DROP TABLE alembic_version")
        connection.commit()

    _run_python("from backend.models.database import init_db; init_db()", database)

    backups = list(tmp_path.glob("legacy.sqlite3.pre-alembic-*.bak"))
    assert len(backups) == 1
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute("SELECT title FROM comic_project WHERE id=1").fetchone()[
                0
            ]
            == "Legacy project"
        )
        assert connection.execute(
            "SELECT summary, status FROM comic_page WHERE id=1"
        ).fetchone() == ("summary", "script_ready")
        assert connection.execute(
            "SELECT seed, generation_run_id FROM comic_image WHERE id=1"
        ).fetchone() == (42, None)
        assert (
            connection.execute(
                "SELECT default_model FROM llm_config WHERE id=1"
            ).fetchone()[0]
            == "model"
        )
        capabilities, bindings, provider, prompt_type = connection.execute(
            "SELECT capabilities_json, bindings_json, provider, prompt_type "
            "FROM image_generation_tool_preset WHERE id=1"
        ).fetchone()
    assert '"txt2img"' in capabilities
    assert '"prompt.positive"' in bindings
    assert '"render.seed"' in bindings
    assert provider == "comfyui"
    assert prompt_type == "natural_language"


def test_character_reference_migration_downgrades_and_upgrades(tmp_path: Path) -> None:
    database = tmp_path / "character-reference.sqlite3"
    _run_python("from backend.models.database import init_db; init_db()", database)
    _run_python(
        "from alembic import command; from alembic.config import Config; "
        "command.downgrade(Config('alembic.ini'), '0005_consistency_evaluation')",
        database,
    )

    with sqlite3.connect(database) as connection:
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert revision == "0005_consistency_evaluation"
    assert "character_reference_generation_task" not in tables
    assert "character_reference_generation_run" not in tables
    assert "character_reference_image" not in tables

    _run_python(
        "from alembic import command; from alembic.config import Config; "
        "command.upgrade(Config('alembic.ini'), 'head')",
        database,
    )
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[
            0
        ] == ("0007_reference_image_catalog")
        assert (
            connection.execute(
                "SELECT count(1) FROM sqlite_master "
                "WHERE type='table' AND name='character_reference_generation_task'"
            ).fetchone()[0]
            == 1
        )


def test_unknown_unversioned_schema_is_rejected_without_stamping(
    tmp_path: Path,
) -> None:
    database = tmp_path / "unknown.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE comic_project (id INTEGER PRIMARY KEY, title TEXT)"
        )
        connection.commit()

    result = _run_python(
        "from backend.models.database import init_db; init_db()",
        database,
        check=False,
    )

    assert result.returncode != 0
    assert "does not match the supported baseline" in result.stderr
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "alembic_version" not in tables
    assert list(tmp_path.glob("unknown.sqlite3.pre-alembic-*.bak")) == []


def test_reference_catalog_upgrade_keeps_legacy_task_images_and_three_roles(tmp_path: Path) -> None:
    """用旧表数据验证增量升级，不把既有三件套扩展成五视图。"""
    database = tmp_path / "reference-history.sqlite3"
    _run_python("from alembic import command; from alembic.config import Config; "
        "command.upgrade(Config('alembic.ini'), '0006_character_reference_generation')", database)
    timestamp = "2026-01-01T00:00:00+00:00"
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO comic_project(id,title,created_at,updated_at) VALUES(1,'History',?,?)", (timestamp, timestamp))
        connection.execute("INSERT INTO session(id,project_id,purpose,thread_id,created_at,updated_at) VALUES(1,1,'outline','legacy-reference',?,?)", (timestamp, timestamp))
        connection.execute("INSERT INTO outline_version(id,project_id,session_id,version_no,content,status,created_at,confirmed_at) VALUES(1,1,1,1,'outline','active',?,?)", (timestamp, timestamp))
        character_columns = ["role", "background", "appearance", "visual_anchors", "negative_constraints",
            "default_hairstyle", "default_clothing", "default_accessories", "default_color_palette"]
        connection.execute("INSERT INTO outline_character(id,outline_version_id,character_key,name," +
            ",".join(character_columns) + ",visual_type,created_at,updated_at) VALUES(1,1,'hero','Hero'," +
            ",".join(["''"] * len(character_columns)) + ",'unknown',?,?)", (timestamp, timestamp))
        connection.execute("INSERT INTO image_generation_tool_preset(id,name,provider,prompt_type,is_default,capabilities_json,bindings_json,endpoint_path,size,response_format,extra_body_json,created_at,updated_at) "
            "VALUES(1,'Legacy','comfyui','hybrid',1,'{}','{}','images/generations','1024x1024','b64_json','{}',?,?)", (timestamp, timestamp))
        connection.execute("INSERT INTO character_reference_generation_task(id,project_id,outline_character_id,tool_preset_id,status,candidate_count,prompt_type,prompt_snapshot_json,progress_json,created_at,updated_at) "
            "VALUES(42,1,1,1,'suspended',1,'hybrid','{}','{}',?,?)", (timestamp, timestamp))
        for index, role in enumerate(("identity_face", "identity_half_body", "identity_full_body"), start=1):
            connection.execute("INSERT INTO character_reference_generation_run(id,task_id,candidate_index,role,seed,provider,prompt_type,positive_prompt,negative_prompt,status,review_status,seed_applied,bindings_json,degradation_json,applied_spec_json,created_at,updated_at) "
                "VALUES(?,42,1,?,99,'comfyui','hybrid','kept positive','kept negative','succeeded','draft',0,'{}','[]','{}',?,?)", (index, role, timestamp, timestamp))
        connection.execute("INSERT INTO character_reference_image(id,run_id,artifact_index,local_path,sha256,created_at,updated_at) VALUES(71,1,1,'outputs/history/face.png',?, ?, ?)", ("a" * 64, timestamp, timestamp))
        connection.commit()
    _run_python("from backend.models.database import init_db; init_db()", database)
    with sqlite3.connect(database) as connection:
        task = connection.execute("SELECT id,outline_character_id,entity_type,entity_id,selected_roles_json,status FROM character_reference_generation_task WHERE id=42").fetchone()
        assert task[:4] == (42, 1, "character", 1)
        import json
        assert json.loads(task[4]) == ["identity_face", "identity_half_body", "identity_full_body"]
        assert task[5] == "suspended"
        assert connection.execute("SELECT id,local_path FROM character_reference_image WHERE id=71").fetchone() == (71, "outputs/history/face.png")
        assert connection.execute("SELECT positive_prompt,seed FROM character_reference_generation_run WHERE id=1").fetchone() == ("kept positive", 99)
        assert {row[1] for row in connection.execute("PRAGMA table_info(generation_task)")} >= {"input_snapshot_json"}
        assert {row[1] for row in connection.execute("PRAGMA table_info(visual_asset)")} >= {"reference_subject_id", "outfit_variant_id"}
