import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import weakref

from PIL import Image
import pytest

from backend.evaluation.runtime import (
    METRIC_VERSION,
    ViStoryBenchProcessRunner,
    _invalid_hashes,
)
from backend.evaluation.vistorybench_worker import (
    _cross_csd_from_reference_baseline,
    _stage,
)
from backend.evaluation import vistorybench_worker


def _image(path: Path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (16, 16), color).save(path)


def test_source_hash_normalizes_platform_line_endings(tmp_path) -> None:
    """同一 Git 源码在 CRLF/LF 工作树中必须通过同一个固定哈希。"""

    source = tmp_path / "source.py"
    source.write_bytes(b"first\r\nsecond\r\n")
    expected = hashlib.sha256(b"first\nsecond\n").hexdigest()

    assert (
        _invalid_hashes(
            tmp_path,
            {"source.py": expected},
            normalize_newlines=True,
        )
        == []
    )
    assert _invalid_hashes(tmp_path, {"source.py": expected}) == ["source.py"]


def test_worker_paths_remain_valid_when_backend_runs_outside_repository(
    tmp_path, monkeypatch
) -> None:
    """隔离目录启动后端时，worker 切回仓库仍要读取同一份评估产物。"""

    monkeypatch.chdir(tmp_path)
    manifest = {"tracks": [{"candidate_index": 1}]}
    result = {"metric_version": METRIC_VERSION, "tracks": []}

    def run_worker(command, *, cwd, **kwargs):
        def child_path(flag):
            path = Path(command[command.index(flag) + 1])
            return path if path.is_absolute() else Path(cwd) / path

        assert json.loads(child_path("--manifest").read_text(encoding="utf-8")) == manifest
        assert child_path("--work-dir") == tmp_path / "outputs" / "evaluation"
        child_path("--result").write_text(json.dumps(result), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="done", stderr="")

    monkeypatch.setattr("backend.evaluation.runtime.subprocess.run", run_worker)

    assert ViStoryBenchProcessRunner().run(
        manifest=manifest, work_dir=Path("outputs/evaluation")
    ) == result
    assert (tmp_path / "outputs/evaluation/worker.stdout.log").read_text() == "done"


def test_worker_releases_cids_models_before_constructing_csd(tmp_path, monkeypatch):
    """CIDS 的实例和共享缓存必须都释放，才能开始下一套 GPU 模型。"""

    model_refs = []
    monkeypatch.setattr(sys, "path", list(sys.path))
    for variable in (
        "API_KEY", "BASE_URL", "MODEL_ID", "OPENAI_API_KEY", "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
    ):
        monkeypatch.setenv(variable, "test-only")

    class Model:
        pass

    class FakeCids:
        _shared_model_cache = {}

        def __init__(self, **kwargs):
            self.model = Model()
            self._shared_model_cache["model"] = self.model
            model_refs.append(weakref.ref(self.model))

        def evaluate(self, **kwargs):
            return {"metrics": {}}

    class FakeCsd:
        def __init__(self, **kwargs):
            assert model_refs[0]() is None, "CIDS model is still held by its evaluator"

    for name in (
        "vistorybench",
        "vistorybench.bench",
        "vistorybench.bench.content",
        "vistorybench.bench.style",
        "vistorybench.bench.content.cids_evaluator",
        "vistorybench.bench.style.csd_evaluator",
    ):
        module = ModuleType(name)
        monkeypatch.setitem(sys.modules, name, module)
        if "." in name:
            parent, child = name.rsplit(".", 1)
            setattr(sys.modules[parent], child, module)
    cids_module = sys.modules["vistorybench.bench.content.cids_evaluator"]
    cids_module.CIDSEvaluator = FakeCids
    cids_module.FaceRestoreHelper = type("FaceRestoreHelper", (), {})
    cids_module.insightface = SimpleNamespace(app=SimpleNamespace(FaceAnalysis=object))
    sys.modules["vistorybench.bench.style.csd_evaluator"].CSDEvaluator = FakeCsd
    monkeypatch.setitem(
        sys.modules, "torch",
        SimpleNamespace(cuda=SimpleNamespace(empty_cache=lambda: None)),
    )
    monkeypatch.setattr(vistorybench_worker, "onnx_cuda_ready", lambda: True)
    monkeypatch.setattr(
        vistorybench_worker, "_stage", lambda *args: (tmp_path, tmp_path, tmp_path)
    )
    monkeypatch.setattr(
        vistorybench_worker, "_cross_csd_from_reference_baseline",
        lambda *args, **kwargs: (0.8, []),
    )

    result = vistorybench_worker.run(
        {
            "pages": [], "characters": [],
            "tracks": [{"candidate_index": 1, "images": [{"path": "placeholder"}]}],
        },
        tmp_path,
    )

    assert result["tracks"][0]["metrics"]["csd_cross"] == 0.8


def test_stage_places_only_reference_assets_in_the_cids_origin_directory(
    tmp_path,
) -> None:
    reference_a = tmp_path / "reference-a.png"
    reference_b = tmp_path / "reference-b.png"
    generated = tmp_path / "generated.png"
    _image(reference_a, (255, 0, 0))
    _image(reference_b, (0, 255, 0))
    _image(generated, (0, 0, 255))
    manifest = {
        "pages": [
            {
                "page_id": 1,
                "page_no": 1,
                "character_keys": ["char_1"],
            }
        ],
        "characters": [
            {
                "key": "char_1",
                "name": "Hero",
                "prompt": "hero",
                "vistorybench_tag": "unrealistic_human",
                "references": [
                    {"path": str(reference_a)},
                    {"path": str(reference_b)},
                ],
            }
        ],
        "tracks": [
            {
                "candidate_index": 1,
                "images": [{"path": str(generated)}],
            }
        ],
    }

    dataset_root, outputs_root, _ = _stage(manifest, tmp_path / "work")

    reference_dir = dataset_root / "ViStory" / "0001" / "image" / "char_1"
    assert [item.name for item in sorted(reference_dir.iterdir())] == [
        "01.jpg",
        "02.jpg",
    ]
    assert (
        outputs_root
        / "comaic"
        / "final"
        / "en"
        / "20000101_000000"
        / "0001"
        / "shots"
        / "shot_00.jpg"
    ).is_file()


def test_cross_csd_compares_each_page_with_approved_references_not_track_images() -> (
    None
):
    class FakeEvaluator:
        scores = {"ref-a-1.png": 0.8, "ref-a-2.png": 0.6, "ref-b.png": 0.4}

        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def _get_csd_score(self, reference: str, generated: str) -> float:
            self.calls.append((reference, generated))
            return self.scores[Path(reference).name]

    manifest = {
        "pages": [
            {"page_id": 1, "page_no": 1, "character_keys": ["char_a"]},
            {"page_id": 2, "page_no": 2, "character_keys": []},
        ],
        "characters": [
            {
                "key": "char_a",
                "references": [
                    {
                        "asset_id": 11,
                        "path": "ref-a-1.png",
                        "role": "identity_face",
                        "version": 1,
                    },
                    {
                        "asset_id": 12,
                        "path": "ref-a-2.png",
                        "role": "identity_full_body",
                        "version": 1,
                    },
                ],
            },
            {
                "key": "char_b",
                "references": [
                    {
                        "asset_id": 21,
                        "path": "ref-b.png",
                        "role": "identity_half_body",
                        "version": 2,
                    }
                ],
            },
        ],
    }
    track = {
        "candidate_index": 1,
        "images": [
            {"page_id": 1, "page_no": 1, "image_id": 101, "path": "gen-1.png"},
            {"page_id": 2, "page_no": 2, "image_id": 102, "path": "gen-2.png"},
        ],
    }
    evaluator = FakeEvaluator()

    score, details = _cross_csd_from_reference_baseline(
        evaluator,
        manifest=manifest,
        track=track,
    )

    assert score == pytest.approx(0.65)
    assert details[0]["score"] == pytest.approx(0.7)
    assert details[0]["fallback_to_all_references"] is False
    assert {item["asset_id"] for item in details[0]["reference_scores"]} == {11, 12}
    assert details[1]["score"] == pytest.approx(0.6)
    assert details[1]["fallback_to_all_references"] is True
    assert len(evaluator.calls) == 5
    assert all(reference.startswith("ref-") for reference, _ in evaluator.calls)
    assert {generated for _, generated in evaluator.calls} == {"gen-1.png", "gen-2.png"}
