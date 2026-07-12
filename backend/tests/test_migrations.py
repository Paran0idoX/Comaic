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


def _run_python(code: str, database: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
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
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        model_table = connection.execute(
            "SELECT count(1) FROM sqlite_master WHERE type='table' AND name='model_profile'"
        ).fetchone()[0]
        spec_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(image_spec)").fetchall()
        }
        tool_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(image_generation_tool_preset)"
            ).fetchall()
        }
        run_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(generation_run)").fetchall()
        }
    assert revision == "0004_image_spec_compilation"
    assert model_table == 0
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT count(1) FROM sqlite_master "
            "WHERE type='table' AND name='image_spec_compilation'"
        ).fetchone()[0] == 1
    assert "prompt_type" in spec_columns
    assert "model_profile_id" not in spec_columns
    assert {"provider", "prompt_type"} <= tool_columns
    assert {"kind", "model_profile_id", "runtime_manifest_json"}.isdisjoint(tool_columns)
    assert {"workflow_hash", "seed_strategy", "provider", "prompt_type"} <= run_columns
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
        assert connection.execute("SELECT title FROM comic_project WHERE id=1").fetchone()[0] == "Legacy project"
        assert connection.execute(
            "SELECT summary, status FROM comic_page WHERE id=1"
        ).fetchone() == ("summary", "script_ready")
        assert connection.execute("SELECT seed, generation_run_id FROM comic_image WHERE id=1").fetchone() == (42, None)
        assert connection.execute("SELECT default_model FROM llm_config WHERE id=1").fetchone()[0] == "model"
        capabilities, bindings, provider, prompt_type = connection.execute(
            "SELECT capabilities_json, bindings_json, provider, prompt_type "
            "FROM image_generation_tool_preset WHERE id=1"
        ).fetchone()
    assert '"txt2img"' in capabilities
    assert '"prompt.positive"' in bindings
    assert '"render.seed"' in bindings
    assert provider == "comfyui"
    assert prompt_type == "natural_language"


def test_unknown_unversioned_schema_is_rejected_without_stamping(tmp_path: Path) -> None:
    database = tmp_path / "unknown.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE comic_project (id INTEGER PRIMARY KEY, title TEXT)")
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
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "alembic_version" not in tables
    assert list(tmp_path.glob("unknown.sqlite3.pre-alembic-*.bak")) == []
