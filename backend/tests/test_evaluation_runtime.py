import hashlib
from pathlib import Path

from PIL import Image
import pytest

from backend.evaluation.runtime import _invalid_hashes
from backend.evaluation.vistorybench_worker import (
    _cross_csd_from_reference_baseline,
    _stage,
)


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
