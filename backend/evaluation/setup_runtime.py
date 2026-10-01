"""显式下载 ViStoryBench 核心指标权重；正常评估运行绝不隐式联网。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from huggingface_hub import snapshot_download
import requests

from backend.evaluation.runtime import (
    VISTORYBENCH_WEIGHTS_REVISION,
    pretrain_root,
    probe_runtime,
)


CORE_WEIGHT_PATTERNS = (
    "groundingdino/**",
    "openai/clip-vit-large-patch14/**",
    "google-bert/bert-base-uncased/**",
    "csd/**",
    "adaface/**",
    "insightface/**",
    "facenet/**",
    "facexlib/**",
)
FACEXLIB_WEIGHTS = {
    "detection_Resnet50_Final.pth": (
        "https://github.com/xinntao/facexlib/releases/download/v0.1.0/"
        "detection_Resnet50_Final.pth",
        "6d1de9c2944f2ccddca5f5e010ea5ae64a39845a86311af6fdf30841b0a5a16d",
    ),
    "parsing_parsenet.pth": (
        "https://github.com/xinntao/facexlib/releases/download/v0.2.2/"
        "parsing_parsenet.pth",
        "3d558d8d0e42c20224f13cf5a29c79eba2d59913419f945545d8cf7b72920de2",
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_lfs_fallback(destination: Path) -> None:
    """代理不兼容 Hub HEAD 请求时，仍从同一官方仓库按 LFS 白名单下载。"""

    git_dir = destination / ".git"
    environment = os.environ.copy()
    environment["GIT_LFS_SKIP_SMUDGE"] = "1"
    if not git_dir.exists():
        subprocess.run(["git", "-C", str(destination), "init"], check=True, env=environment)
        subprocess.run(
            [
                "git",
                "-C",
                str(destination),
                "remote",
                "add",
                "origin",
                "https://huggingface.co/ViStoryBench/VistoryBench_pretrain",
            ],
            check=True,
            env=environment,
        )
    current = subprocess.run(
        ["git", "-C", str(destination), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    ).stdout.strip()
    if current != VISTORYBENCH_WEIGHTS_REVISION:
        try:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(destination),
                    "fetch",
                    "--depth=1",
                    "origin",
                    VISTORYBENCH_WEIGHTS_REVISION,
                ],
                check=True,
                env=environment,
            )
        except subprocess.CalledProcessError:
            # 部分企业代理拒绝按对象哈希 fetch；只有远端 main 仍精确指向
            # 固定提交时才允许回退，绝不静默升级权重版本。
            subprocess.run(
                ["git", "-C", str(destination), "fetch", "--depth=1", "origin", "main"],
                check=True,
                env=environment,
            )
            fetched = subprocess.run(
                ["git", "-C", str(destination), "rev-parse", "FETCH_HEAD"],
                capture_output=True,
                text=True,
                check=True,
                env=environment,
            ).stdout.strip()
            if fetched != VISTORYBENCH_WEIGHTS_REVISION:
                raise RuntimeError(
                    "Official weight repository main no longer matches the pinned revision"
                )
        subprocess.run(
            ["git", "-C", str(destination), "checkout", "--detach", "FETCH_HEAD"],
            check=True,
            env=environment,
        )
    subprocess.run(
        [
            "git",
            "-C",
            str(destination),
            "lfs",
            "pull",
            "-I",
            ",".join(CORE_WEIGHT_PATTERNS),
        ],
        check=True,
        env=environment,
    )


def _download_file(url: str, destination: Path, expected_sha256: str) -> None:
    if destination.is_file() and _sha256(destination) == expected_sha256:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(f"{destination.suffix}.part")
    with requests.get(url, stream=True, timeout=(30, 600)) as response:
        response.raise_for_status()
        with partial.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    partial.replace(destination)
    if _sha256(destination) != expected_sha256:
        raise RuntimeError(f"Downloaded file failed SHA-256 verification: {destination}")


def download_core_weights(destination: Path) -> Path:
    """从 ViStoryBench 官方 Hugging Face 仓库物化核心权重。"""

    destination.mkdir(parents=True, exist_ok=True)
    try:
        snapshot_download(
            repo_id="ViStoryBench/VistoryBench_pretrain",
            repo_type="model",
            revision=VISTORYBENCH_WEIGHTS_REVISION,
            local_dir=destination,
            allow_patterns=list(CORE_WEIGHT_PATTERNS),
        )
    except Exception:
        _git_lfs_fallback(destination)
    # 某些代理会让 snapshot_download 提前返回但只留下 LFS pointer；
    # 在这种情况下继续走同一官方仓库的 Git LFS 物化路径。
    snapshot_readiness = probe_runtime()
    if snapshot_readiness.missing_weights or snapshot_readiness.invalid_weights:
        _git_lfs_fallback(destination)
    for filename, (url, expected_sha256) in FACEXLIB_WEIGHTS.items():
        _download_file(
            url,
            destination / "facexlib" / "weights" / filename,
            expected_sha256,
        )
    readiness = probe_runtime()
    if readiness.missing_weights or readiness.invalid_weights:
        raise RuntimeError(
            "ViStoryBench weights are incomplete or invalid: "
            f"missing={readiness.missing_weights}, invalid={readiness.invalid_weights}"
        )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if args.download:
        download_core_weights(pretrain_root())
    print(json.dumps(probe_runtime().to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
