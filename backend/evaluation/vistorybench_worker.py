"""把 Comaic 轨道转换成 ViStoryBench 最小数据集并执行 CIDS/CSD。"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import gc
import json
import os
from pathlib import Path
import sys
from typing import Any

from PIL import Image

from backend.evaluation import REFERENCE_BASELINE_MODE
from backend.evaluation.runtime import (
    METRIC_VERSION,
    onnx_cuda_ready,
    pretrain_root,
    vistorybench_root,
)


METHOD = "comaic"
MODE = "final"
LANGUAGE = "en"
OUTPUT_TIMESTAMP = "20000101_000000"


@contextmanager
def _working_directory(path: Path):
    """仅在官方配置解析期间切换目录，兼容其相对 config.yaml 约定。"""

    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _rgb_jpg(source: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image.convert("RGB").save(destination, format="JPEG", quality=95)


def _story_json(manifest: dict[str, Any]) -> dict[str, Any]:
    characters = {
        item["key"]: {
            "name_en": item["name"],
            "name_ch": item["name"],
            "prompt_en": item.get("prompt") or item["name"],
            "prompt_ch": item.get("prompt") or item["name"],
            "tag": item["vistorybench_tag"],
            "num_of_appearances": sum(
                item["key"] in page["character_keys"] for page in manifest["pages"]
            ),
        }
        for item in manifest["characters"]
    }
    shots = []
    for shot_index, page in enumerate(manifest["pages"]):
        character_names = [
            characters[key]["name_en"]
            for key in page["character_keys"]
            if key in characters
        ]
        shots.append(
            {
                "index": shot_index,
                "Setting Description": {
                    "en": page.get("scene") or "",
                    "ch": page.get("scene") or "",
                },
                "Plot Correspondence": {
                    "en": page.get("summary") or "",
                    "ch": page.get("summary") or "",
                },
                "Characters Appearing": {
                    "en": page["character_keys"],
                    "ch": character_names,
                },
                "Static Shot Description": {
                    "en": page.get("description") or "",
                    "ch": page.get("description") or "",
                },
                "Shot Perspective Design": {
                    "en": page.get("composition") or "",
                    "ch": page.get("composition") or "",
                },
            }
        )
    return {
        "Story_type": {"en": "Comic", "ch": "漫画"},
        "Characters": characters,
        "Shots": shots,
    }


def _stage(manifest: dict[str, Any], work_dir: Path) -> tuple[Path, Path, Path]:
    dataset_root = work_dir / "dataset"
    outputs_root = work_dir / "outputs"
    results_root = work_dir / "results"
    story_template = _story_json(manifest)
    for track_no, track in enumerate(manifest["tracks"], start=1):
        story_id = f"{track_no:04d}"
        story_root = dataset_root / "ViStory" / story_id
        story_root.mkdir(parents=True, exist_ok=True)
        (story_root / "story.json").write_text(
            json.dumps(story_template, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for character in manifest["characters"]:
            for ref_index, reference in enumerate(character["references"], start=1):
                _rgb_jpg(
                    reference["path"],
                    story_root / "image" / character["key"] / f"{ref_index:02d}.jpg",
                )
        output_story = (
            outputs_root
            / METHOD
            / MODE
            / LANGUAGE
            / OUTPUT_TIMESTAMP
            / story_id
            / "shots"
        )
        for shot_index, image in enumerate(track["images"]):
            _rgb_jpg(image["path"], output_story / f"shot_{shot_index:02d}.jpg")
    return dataset_root, outputs_root, results_root


def _release_cids(evaluator_class: Any, evaluator: Any) -> None:
    del evaluator
    evaluator_class._shared_model_cache.clear()
    gc.collect()
    try:
        import torch

        torch.cuda.empty_cache()
    except Exception:
        pass


def _normalize_cids(
    result: dict[str, Any],
    *,
    repeated_character_keys: set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics = dict(result.get("metrics") or {})
    per_character = result.get("cids") or {}
    repeated_values = [
        float(record["self"])
        for key, record in per_character.items()
        if key in repeated_character_keys
        and isinstance(record, dict)
        and isinstance(record.get("self"), (int, float))
    ]
    applicability = {
        "cids_cross": True,
        "cids_self": bool(repeated_values),
        "occm": True,
        "copy_paste": True,
    }
    if repeated_values:
        metrics["cids_self_mean"] = sum(repeated_values) / len(repeated_values)
    else:
        metrics["cids_self_mean"] = None
    return metrics, {"per_character": per_character, "applicability": applicability}


def _reference_baseline_details(manifest: dict[str, Any]) -> dict[str, Any]:
    """返回不含本地路径的参考基准快照，供结果审计和前端展示。"""

    baseline = manifest.get("reference_baseline") or {}
    return {
        "mode": baseline.get("mode", REFERENCE_BASELINE_MODE),
        "reference_count": int(baseline.get("reference_count") or 0),
        "characters": baseline.get("characters") or [],
    }


def _cross_csd_from_reference_baseline(
    evaluator: Any,
    *,
    manifest: dict[str, Any],
    track: dict[str, Any],
) -> tuple[float, list[dict[str, Any]]]:
    """按页面出场角色，把生成图与其全部已批准参考图计算 Cross CSD。"""

    characters = {item["key"]: item for item in manifest["characters"]}
    pages = {int(item["page_id"]): item for item in manifest["pages"]}
    all_references = [
        (character_key, reference)
        for character_key, character in characters.items()
        for reference in character.get("references") or []
    ]
    shot_scores: list[float] = []
    shot_details: list[dict[str, Any]] = []
    for image in track["images"]:
        page = pages.get(int(image["page_id"]))
        character_keys = (page.get("character_keys") or []) if page else []
        references = [
            (character_key, reference)
            for character_key in character_keys
            for reference in characters.get(character_key, {}).get("references") or []
        ]
        # 无角色页面仍以同一任务的身份参考图衡量整体画风，不回退到候选轨道首图。
        fallback_to_all = not references
        if fallback_to_all:
            references = all_references
        if not references:
            raise RuntimeError("Reference baseline contains no usable identity image")

        reference_scores = []
        for character_key, reference in references:
            score = float(
                evaluator._get_csd_score(  # noqa: SLF001 - 固定版官方 evaluator 的特征入口
                    reference["path"],
                    image["path"],
                )
            )
            reference_scores.append(
                {
                    "character_key": character_key,
                    "asset_id": int(reference["asset_id"]),
                    "role": reference["role"],
                    "version": int(reference["version"]),
                    "score": score,
                }
            )
        shot_score = sum(item["score"] for item in reference_scores) / len(
            reference_scores
        )
        shot_scores.append(shot_score)
        shot_details.append(
            {
                "page_id": int(image["page_id"]),
                "page_no": int(image["page_no"]),
                "image_id": int(image["image_id"]),
                "score": shot_score,
                "fallback_to_all_references": fallback_to_all,
                "reference_scores": reference_scores,
            }
        )
    if not shot_scores:
        raise RuntimeError("Candidate track contains no image for Cross CSD")
    return sum(shot_scores) / len(shot_scores), shot_details


def run(manifest: dict[str, Any], work_dir: Path) -> dict[str, Any]:
    # CIDS 还包含一个可选 GPT-V 动作评分。它不属于 Comaic 的准出指标，
    # 并且官方实现会从通用环境变量读取凭据；评估子进程必须彻底离线，
    # 避免开发机恰好存在 API_KEY 时产生未授权的外部请求和费用。
    for variable in ("API_KEY", "BASE_URL", "MODEL_ID", "OPENAI_API_KEY"):
        os.environ.pop(variable, None)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    work_dir = work_dir.resolve()
    source_root = vistorybench_root()
    sys.path.insert(0, str(source_root))
    dataset_root, outputs_root, results_root = _stage(manifest, work_dir)
    # 官方 GroundingDINO_SwinT_OGC.py 会直接 open('config.yaml')，
    # 这里只提供它实际需要的本地 pretrain 路径，不改动固定版上游源码。
    (work_dir / "config.yaml").write_text(
        json.dumps({"core": {"paths": {"pretrain": str(pretrain_root())}}}),
        encoding="utf-8",
    )
    config = {
        "core": {
            "paths": {
                "dataset": str(dataset_root),
                "outputs": str(outputs_root),
                "pretrain": str(pretrain_root()),
                "results": str(results_root),
            },
            "runtime": {"device": "cuda"},
        },
        "evaluators": {
            "cids": {
                # origin 强制 CIDS 从 _stage 写入的批准参考图目录取特征，
                # 禁止把候选轨道中的任意生成图当作身份基准。
                "ref_mode": "origin",
                "use_multi_face_encoder": True,
                "ensemble_method": "average",
                "detection": {"dino": {"box_threshold": 0.25, "text_threshold": 0.25}},
                "encoders": {"clip": {"model_id": "openai/clip-vit-large-patch14"}},
                "matching": {"superfluous_threshold": 0.8, "topk_per_nochar": 5},
                "ensemble_weights": {"arcface": 0.4, "adaface": 0.4, "facenet": 0.2},
            },
            "csd": {"cache_limit": 64},
        },
    }
    import vistorybench.bench.content.cids_evaluator as cids_module
    from vistorybench.bench.style.csd_evaluator import CSDEvaluator

    # 官方 CIDS 未传 model_rootpath，facexlib 默认会在首次运行时联网下载。
    # 这里显式指向 setup_runtime 已物化的权重目录，保持评估阶段离线可复现。
    original_face_helper = cids_module.FaceRestoreHelper
    original_face_analysis = cids_module.insightface.app.FaceAnalysis

    class OfflineFaceRestoreHelper(original_face_helper):
        def __init__(self, *args, **kwargs):
            kwargs["model_rootpath"] = str(pretrain_root() / "facexlib" / "weights")
            super().__init__(*args, **kwargs)

    cids_module.FaceRestoreHelper = OfflineFaceRestoreHelper
    if not onnx_cuda_ready():

        def cpu_compatible_face_analysis(*args, providers=None, **kwargs):
            if providers == ["CUDAExecutionProvider"]:
                raise RuntimeError(
                    "ONNX Runtime CUDA 12/cuDNN 9 libraries are unavailable; using CPU fallback"
                )
            return original_face_analysis(*args, providers=providers, **kwargs)

        cids_module.insightface.app.FaceAnalysis = cpu_compatible_face_analysis
    CIDSEvaluator = cids_module.CIDSEvaluator

    occurrence_count = {
        character["key"]: sum(
            character["key"] in page["character_keys"] for page in manifest["pages"]
        )
        for character in manifest["characters"]
    }
    repeated_keys = {key for key, count in occurrence_count.items() if count >= 2}
    track_payloads: dict[int, dict[str, Any]] = {
        int(track["candidate_index"]): {
            "candidate_index": int(track["candidate_index"]),
            "metrics": {},
            "details": {
                "reference_baseline": _reference_baseline_details(manifest),
            },
            "applicability": {},
        }
        for track in manifest["tracks"]
    }

    with _working_directory(work_dir):
        cids = CIDSEvaluator(
            config=config,
            timestamp=OUTPUT_TIMESTAMP,
            mode=MODE,
            language=LANGUAGE,
            outputs_timestamp=OUTPUT_TIMESTAMP,
        )
    for track_no, track in enumerate(manifest["tracks"], start=1):
        result = cids.evaluate(method=METHOD, story_id=f"{track_no:04d}")
        if not isinstance(result, dict):
            raise RuntimeError(
                f"CIDS returned no result for candidate {track['candidate_index']}"
            )
        normalized, detail = _normalize_cids(
            result, repeated_character_keys=repeated_keys
        )
        payload = track_payloads[int(track["candidate_index"])]
        payload["metrics"].update(
            {
                "cids_cross": normalized.get("cids_cross_mean"),
                "cids_self": normalized.get("cids_self_mean"),
                "occm": normalized.get("occm"),
                "copy_paste": normalized.get("copy_paste_score"),
            }
        )
        payload["applicability"].update(detail.pop("applicability"))
        payload["details"]["cids"] = detail
    _release_cids(CIDSEvaluator, cids)

    csd = CSDEvaluator(
        config=config,
        timestamp=OUTPUT_TIMESTAMP,
        mode=MODE,
        language=LANGUAGE,
        outputs_timestamp=OUTPUT_TIMESTAMP,
    )
    for track in manifest["tracks"]:
        image_paths = [image["path"] for image in track["images"]]
        csd_self_applicable = len(image_paths) >= 2
        self_csd = csd.get_self_csd_score(image_paths) if csd_self_applicable else None
        cross_csd, shot_details = _cross_csd_from_reference_baseline(
            csd,
            manifest=manifest,
            track=track,
        )
        payload = track_payloads[int(track["candidate_index"])]
        payload["metrics"].update(
            {
                "csd_cross": cross_csd,
                "csd_self": self_csd,
            }
        )
        payload["applicability"].update(
            {"csd_cross": True, "csd_self": csd_self_applicable}
        )
        payload["details"]["csd"] = {"shot_details": shot_details}
    del csd
    gc.collect()
    try:
        import torch

        torch.cuda.empty_cache()
    except Exception:
        pass
    return {
        "metric_version": METRIC_VERSION,
        "tracks": [track_payloads[key] for key in sorted(track_payloads)],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--work-dir", required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    result = run(manifest, Path(args.work_dir))
    Path(args.result).write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
