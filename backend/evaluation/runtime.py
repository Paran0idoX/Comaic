"""ViStoryBench 环境探测与同解释器子进程调用。"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from functools import lru_cache
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


VISTORYBENCH_COMMIT = "b44ec9108668cc2bcc8c5280886b235e9fb8bea9"
VISTORYBENCH_WEIGHTS_REVISION = "285483b0470a4d7f30533889d35dd749933e67ba"
METRIC_VERSION = f"vistorybench:{VISTORYBENCH_COMMIT[:8]}:comaic-adapter-v4"
REQUIRED_MODULES = (
    "torch",
    "torchvision",
    "transformers",
    "groundingdino",
    "insightface",
    "onnxruntime",
    "facexlib",
    "cv2",
    "scipy",
    "PIL",
)
REQUIRED_WEIGHT_PATHS = (
    "groundingdino/weights/groundingdino_swint_ogc.pth",
    "openai/clip-vit-large-patch14/config.json",
    "openai/clip-vit-large-patch14/merges.txt",
    "openai/clip-vit-large-patch14/model.safetensors",
    "openai/clip-vit-large-patch14/preprocessor_config.json",
    "openai/clip-vit-large-patch14/special_tokens_map.json",
    "openai/clip-vit-large-patch14/tokenizer_config.json",
    "openai/clip-vit-large-patch14/tokenizer.json",
    "openai/clip-vit-large-patch14/vocab.json",
    "google-bert/bert-base-uncased/config.json",
    "google-bert/bert-base-uncased/model.safetensors",
    "google-bert/bert-base-uncased/tokenizer_config.json",
    "google-bert/bert-base-uncased/tokenizer.json",
    "google-bert/bert-base-uncased/vocab.txt",
    "csd/csd_vit-large.pth",
    "adaface/adaface_ir101_webface12m.ckpt",
    "insightface/models/antelopev2/1k3d68.onnx",
    "insightface/models/antelopev2/2d106det.onnx",
    "insightface/models/antelopev2/genderage.onnx",
    "insightface/models/antelopev2/glintr100.onnx",
    "insightface/models/antelopev2/scrfd_10g_bnkps.onnx",
    "facenet/20180402-114759-vggface2.pt",
    "facexlib/weights/detection_Resnet50_Final.pth",
    "facexlib/weights/parsing_parsenet.pth",
)
REQUIRED_SOURCE_HASHES = {
    "vistorybench/bench/content/cids_evaluator.py": (
        "896767fe0beefe14b8177987cee6bfcbd825a95a4a9af53159e8e5ecb762d987"
    ),
    "vistorybench/bench/content/AdaFace/inference.py": (
        "5c0758cb3218ccf8c5ebfcaea71aca59da7332e94c0c2a57dbe87bc21b4f8cfa"
    ),
    "vistorybench/bench/content/GroundingDINO_SwinT_OGC.py": (
        "ebe84f20f428b5ec44572291303d7fdb45b5c5dad68db786b9596ccfc95ae138"
    ),
    "vistorybench/bench/style/csd_evaluator.py": (
        "6ad025c345ec200ad82f95d82ef40b4b91f933b7c395dae4b90b5de4e825da8f"
    ),
    "LICENSE": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
}
REQUIRED_WEIGHT_HASHES = {
    "groundingdino/weights/groundingdino_swint_ogc.pth": (
        "3b3ca2563c77c69f651d7bd133e97139c186df06231157a64c507099c52bc799"
    ),
    "openai/clip-vit-large-patch14/config.json": (
        "69aeaf94038c553e63b75e8a377f8ebdeb9cb4ed0fa8a10fc96f7572450cbc8f"
    ),
    "openai/clip-vit-large-patch14/model.safetensors": (
        "a2bf730a0c7debf160f7a6b50b3aaf3703e7e88ac73de7a314903141db026dcb"
    ),
    "openai/clip-vit-large-patch14/preprocessor_config.json": (
        "03ad9c3cfa555d6b365f0ed33b5d3c837fc68cf672cf1250ed827f2d7de1e875"
    ),
    "openai/clip-vit-large-patch14/tokenizer.json": (
        "d8483621960b395897effb946c20bc38394e31b28d9b862c7d320a69f845c8a1"
    ),
    "google-bert/bert-base-uncased/config.json": (
        "b92c83fdd39b9dcdded83e388feefd12a9bfc6e4e81cda9328c73b6865b10b3f"
    ),
    "google-bert/bert-base-uncased/model.safetensors": (
        "68d45e234eb4a928074dfd868cead0219ab85354cc53d20e772753c6bb9169d3"
    ),
    "google-bert/bert-base-uncased/tokenizer_config.json": (
        "a025160ef0431f1a392f6f050c1310f4c5d9fb6f275932dbccba73c4d214bf10"
    ),
    "google-bert/bert-base-uncased/tokenizer.json": (
        "ce64fce797c24f68df90b40a3f74f579b336a493db14bd583fd520ea0d8c9a98"
    ),
    "google-bert/bert-base-uncased/vocab.txt": (
        "b49e80874c5efbc7f4cde245a812673b05ef1360ced56b8bc8c750eaeef3fe0f"
    ),
    "csd/csd_vit-large.pth": (
        "2e4f463ac52e889bc39247060a3243d0eafff6b757e4e8e44a1830c20ab5af41"
    ),
    "adaface/adaface_ir101_webface12m.ckpt": (
        "0e7a3238d2a50f3fe3860782534928ac7cb2598977cf897f6869fd5ac2493fd0"
    ),
    "insightface/models/antelopev2/1k3d68.onnx": (
        "df5c06b8a0c12e422b2ed8947b8869faa4105387f199c477af038aa01f9a45cc"
    ),
    "insightface/models/antelopev2/2d106det.onnx": (
        "f001b856447c413801ef5c42091ed0cd516fcd21f2d6b79635b1e733a7109dbf"
    ),
    "insightface/models/antelopev2/genderage.onnx": (
        "4fde69b1c810857b88c64a335084f1c3fe8f01246c9a191b48c7bb756d6652fb"
    ),
    "insightface/models/antelopev2/glintr100.onnx": (
        "4ab1d6435d639628a6f3e5008dd4f929edf4c4124b1a7169e1048f9fef534cdf"
    ),
    "insightface/models/antelopev2/scrfd_10g_bnkps.onnx": (
        "5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91"
    ),
    "facenet/20180402-114759-vggface2.pt": (
        "281cebca8662831adb987a874bdcb36e73f5b1c6dc5ee5878f305e985625d99b"
    ),
    "facexlib/weights/detection_Resnet50_Final.pth": (
        "6d1de9c2944f2ccddca5f5e010ea5ae64a39845a86311af6fdf30841b0a5a16d"
    ),
    "facexlib/weights/parsing_parsenet.pth": (
        "3d558d8d0e42c20224f13cf5a29c79eba2d59913419f945545d8cf7b72920de2"
    ),
}


@lru_cache(maxsize=64)
def _file_sha256(path_text: str, size: int, mtime_ns: int) -> str:
    """按文件状态缓存大权重哈希，避免每次读取设置页都扫描数 GB。"""

    del size, mtime_ns
    digest = hashlib.sha256()
    with Path(path_text).open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=32)
def _normalized_source_sha256(path_text: str, size: int, mtime_ns: int) -> str:
    """源码按 LF 规范化后校验，避免同一 Git 提交在 Windows 被 CRLF 误判。"""

    del size, mtime_ns
    content = Path(path_text).read_bytes()
    normalized = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(normalized).hexdigest()


def _invalid_hashes(
    root: Path,
    expected: dict[str, str],
    *,
    normalize_newlines: bool = False,
) -> list[str]:
    invalid: list[str] = []
    for relative_path, expected_digest in expected.items():
        path = root / relative_path
        if not path.is_file():
            continue
        try:
            stat = path.stat()
            hasher = _normalized_source_sha256 if normalize_newlines else _file_sha256
            actual = hasher(str(path), stat.st_size, stat.st_mtime_ns)
        except OSError:
            invalid.append(relative_path)
            continue
        if actual.lower() != expected_digest.lower():
            invalid.append(relative_path)
    return invalid


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def vistorybench_root() -> Path:
    configured = os.getenv("VISTORYBENCH_ROOT")
    return (
        Path(configured).resolve()
        if configured
        else repository_root() / "third_party" / "vistorybench"
    )


def pretrain_root() -> Path:
    configured = os.getenv("VISTORYBENCH_PRETRAIN_PATH")
    return (
        Path(configured).resolve()
        if configured
        else repository_root() / "data" / "models" / "vistorybench"
    )


def onnx_cuda_ready() -> bool:
    """判断 ONNX Runtime 的 CUDA 12/cuDNN 9 动态库是否真的可加载。"""

    try:
        import onnxruntime

        if "CUDAExecutionProvider" not in onnxruntime.get_available_providers():
            return False
        libraries = (
            ("cublasLt64_12.dll", "cudnn64_9.dll")
            if os.name == "nt"
            else ("libcublasLt.so.12", "libcudnn.so.9")
        )
        loader = ctypes.WinDLL if os.name == "nt" else ctypes.CDLL
        for library in libraries:
            loader(library)
        return True
    except (ImportError, OSError):
        return False


@dataclass(slots=True)
class RuntimeReadiness:
    ready: bool
    python_executable: str
    source_root: str
    pretrain_root: str
    missing_modules: list[str]
    missing_source_files: list[str]
    missing_weights: list[str]
    invalid_source_files: list[str] = field(default_factory=list)
    invalid_weights: list[str] = field(default_factory=list)
    onnx_cuda_available: bool = False
    arcface_provider: str = "cpu"
    torch_version: str | None = None
    cuda_available: bool = False
    cuda_device: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "python_executable": self.python_executable,
            "source_root": self.source_root,
            "pretrain_root": self.pretrain_root,
            "missing_modules": self.missing_modules,
            "missing_source_files": self.missing_source_files,
            "missing_weights": self.missing_weights,
            "invalid_source_files": self.invalid_source_files,
            "invalid_weights": self.invalid_weights,
            "onnx_cuda_available": self.onnx_cuda_available,
            "arcface_provider": self.arcface_provider,
            "torch_version": self.torch_version,
            "cuda_available": self.cuda_available,
            "cuda_device": self.cuda_device,
            "detail": self.detail,
            "metric_version": METRIC_VERSION,
        }


def probe_runtime() -> RuntimeReadiness:
    """不触发下载，只报告代码、依赖、权重和 CUDA 是否就绪。"""

    source_root = vistorybench_root()
    weights_root = pretrain_root()
    missing_modules = [
        name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None
    ]
    required_source_files = tuple(REQUIRED_SOURCE_HASHES)
    missing_source_files = [
        name for name in required_source_files if not (source_root / name).exists()
    ]
    missing_weights = [
        name for name in REQUIRED_WEIGHT_PATHS if not (weights_root / name).exists()
    ]
    invalid_source_files = _invalid_hashes(
        source_root,
        REQUIRED_SOURCE_HASHES,
        normalize_newlines=True,
    )
    invalid_weights = _invalid_hashes(weights_root, REQUIRED_WEIGHT_HASHES)
    torch_version = None
    cuda_available = False
    cuda_device = None
    detail = None
    onnx_cuda_available = False
    if "onnxruntime" not in missing_modules:
        onnx_cuda_available = onnx_cuda_ready()
    if "torch" not in missing_modules:
        try:
            import torch

            torch_version = str(torch.__version__)
            cuda_available = bool(torch.cuda.is_available())
            if cuda_available:
                cuda_device = str(torch.cuda.get_device_name(0))
        except Exception as exc:  # noqa: BLE001 - readiness 必须返回诊断而不是导致启动失败
            detail = str(exc)
    ready = not (
        missing_modules
        or missing_source_files
        or missing_weights
        or invalid_source_files
        or invalid_weights
        or not cuda_available
    )
    return RuntimeReadiness(
        ready=ready,
        python_executable=sys.executable,
        source_root=str(source_root),
        pretrain_root=str(weights_root),
        missing_modules=missing_modules,
        missing_source_files=missing_source_files,
        missing_weights=missing_weights,
        invalid_source_files=invalid_source_files,
        invalid_weights=invalid_weights,
        onnx_cuda_available=onnx_cuda_available,
        arcface_provider="cuda" if onnx_cuda_available else "cpu",
        torch_version=torch_version,
        cuda_available=cuda_available,
        cuda_device=cuda_device,
        detail=detail,
    )


class ViStoryBenchProcessRunner:
    """使用当前 comaic 解释器运行官方指标，并读取结构化结果文件。"""

    def __init__(self, *, timeout_seconds: float = 7200.0):
        self.timeout_seconds = timeout_seconds

    def run(
        self,
        *,
        manifest: dict[str, Any],
        work_dir: Path,
    ) -> dict[str, Any]:
        # worker 会切换到仓库目录导入代码；先固定调用方的产物目录，避免读错相对路径。
        work_dir = work_dir.resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = work_dir / "manifest.json"
        result_path = work_dir / "result.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        command = [
            sys.executable,
            "-m",
            "backend.evaluation.vistorybench_worker",
            "--manifest",
            str(manifest_path),
            "--result",
            str(result_path),
            "--work-dir",
            str(work_dir),
        ]
        completed = subprocess.run(
            command,
            cwd=repository_root(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout_seconds,
            check=False,
        )
        (work_dir / "worker.stdout.log").write_text(
            completed.stdout[-200_000:], encoding="utf-8"
        )
        (work_dir / "worker.stderr.log").write_text(
            completed.stderr[-200_000:], encoding="utf-8"
        )
        if completed.returncode != 0:
            message = (
                completed.stderr or completed.stdout or "ViStoryBench worker failed"
            )[-4000:]
            raise RuntimeError(
                f"ViStoryBench worker exited with {completed.returncode}: {message}"
            )
        if not result_path.exists():
            raise RuntimeError("ViStoryBench worker did not create result.json")
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("tracks"), list):
            raise RuntimeError(
                "ViStoryBench worker returned an invalid result contract"
            )
        return payload
