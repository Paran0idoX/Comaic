import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_application_starts_and_exposes_p0_routes(tmp_path: Path) -> None:
    database = tmp_path / "api.sqlite3"
    code = """
import asyncio
from sqlalchemy import inspect

from backend.main import app, health
from backend.models.database import engine

paths = {route.path for route in app.routes}
assert '/api/image-specs/script-tasks/{task_id}/compile/stream' in paths
assert '/api/image-specs/presets' in paths
assert '/api/visual-bible/projects/{project_id}/assets/upload' in paths
assert '/api/visual-bible/configurations/{kind}/{item_id}/status' in paths
assert '/api/visual-bible/assets/{asset_id}/status' in paths
assert '/api/image-generation/runs/{run_id}' in paths
assert all(not path.startswith('/api/image-prompts') for path in paths)

async def smoke():
    async with app.router.lifespan_context(app):
        assert health() == {'status': 'ok'}
        inspector = inspect(engine)
        assert 'model_profile' not in inspector.get_table_names()
        spec_columns = {item['name'] for item in inspector.get_columns('image_spec')}
        assert 'prompt_type' in spec_columns
        assert 'model_profile_id' not in spec_columns

asyncio.run(smoke())
"""
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database}"
    environment["PYTHONPATH"] = os.pathsep.join(
        value
        for value in (str(ROOT), environment.get("PYTHONPATH"))
        if value
    )
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=environment,
        check=True,
        text=True,
        capture_output=True,
    )
