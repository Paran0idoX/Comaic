import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_application_starts_and_exposes_p0_routes(tmp_path: Path) -> None:
    database = tmp_path / "api.sqlite3"
    code = """
import asyncio
from sqlalchemy import select

from backend.main import app, health
from backend.models.comic import ModelProfile
from backend.models.database import SessionLocal

paths = {route.path for route in app.routes}
assert '/api/image-specs/script-tasks/{task_id}/compile/stream' in paths
assert '/api/visual-bible/projects/{project_id}/assets/upload' in paths
assert '/api/visual-bible/configurations/{kind}/{item_id}/status' in paths
assert '/api/visual-bible/assets/{asset_id}/status' in paths
assert '/api/image-generation/runs/{run_id}' in paths

async def smoke():
    async with app.router.lifespan_context(app):
        assert health() == {'status': 'ok'}
        with SessionLocal() as session:
            profiles = list(session.scalars(select(ModelProfile)))
            assert {item.family.value for item in profiles} == {'anima', 'z_image'}

asyncio.run(smoke())
"""
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database}"
    environment["PYTHONPATH"] = str(ROOT)
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=environment,
        check=True,
        text=True,
        capture_output=True,
    )
