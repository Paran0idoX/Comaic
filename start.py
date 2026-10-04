from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = PROJECT_ROOT / "backend"
CONDA_REEXEC_MARKER = "COMAIC_CONDA_REEXEC"
WATCHED_BACKEND_SUFFIXES = {".py", ".md", ".json", ".cfg", ".toml", ".yaml", ".yml"}


class LauncherError(RuntimeError):
    """开发服务无法启动或热重载时抛出的可读错误。"""


@dataclass(frozen=True, slots=True)
class DevConfig:
    """集中保存启动参数，允许开发者通过环境变量覆盖默认值。"""

    conda_env_name: str
    backend_host: str
    backend_health_host: str
    backend_port: int
    backend_startup_timeout: int
    frontend_host: str
    frontend_port: int

    @classmethod
    def from_environment(cls) -> "DevConfig":
        backend_host = _env_text("BACKEND_HOST", "127.0.0.1")
        default_health_host = "127.0.0.1" if backend_host in {"0.0.0.0", "::"} else backend_host
        return cls(
            conda_env_name=_env_text("CONDA_ENV_NAME", "comaic"),
            backend_host=backend_host,
            backend_health_host=_env_text("BACKEND_HEALTH_HOST", default_health_host),
            backend_port=_env_port("BACKEND_PORT", 8000),
            backend_startup_timeout=_env_positive_int("BACKEND_STARTUP_TIMEOUT", 60),
            frontend_host=_env_text("FRONTEND_HOST", "127.0.0.1"),
            frontend_port=_env_port("FRONTEND_PORT", 5173),
        )

    @property
    def backend_url(self) -> str:
        return _http_url(self.backend_host, self.backend_port)

    @property
    def backend_health_url(self) -> str:
        return f"{_http_url(self.backend_health_host, self.backend_port)}/health"

    @property
    def frontend_url(self) -> str:
        return _http_url(self.frontend_host, self.frontend_port)


def _env_text(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _env_positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise LauncherError(f"{name} must be a positive integer, got {raw_value!r}.") from exc
    if value <= 0:
        raise LauncherError(f"{name} must be a positive integer, got {raw_value!r}.")
    return value


def _env_port(name: str, default: int) -> int:
    value = _env_positive_int(name, default)
    if value > 65535:
        raise LauncherError(f"{name} must be between 1 and 65535, got {value}.")
    return value


def _http_url(host: str, port: int) -> str:
    url_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"http://{url_host}:{port}"


def _find_conda() -> str | None:
    candidates = ("conda.exe", "conda.bat", "conda") if os.name == "nt" else ("conda",)
    return next((path for name in candidates if (path := shutil.which(name))), None)


def _relaunch_in_conda_environment(env_name: str) -> int | None:
    """脚本可由任意 Python 启动；必要时自动在目标 conda 环境中重新执行自身。"""

    if os.getenv(CONDA_REEXEC_MARKER) == "1" or Path(sys.prefix).name.casefold() == env_name.casefold():
        return None

    conda = _find_conda()
    if conda is None:
        raise LauncherError(f"conda was not found; activate the {env_name!r} environment first.")

    print(f"[launcher] Re-launching in conda environment: {env_name}", flush=True)
    environment = os.environ.copy()
    environment[CONDA_REEXEC_MARKER] = "1"
    conda_command = [
        conda,
        "run",
        "--no-capture-output",
        "-n",
        env_name,
        "python",
        str(Path(__file__).resolve()),
        *sys.argv[1:],
    ]
    if os.name == "nt" and Path(conda).suffix.casefold() in {".bat", ".cmd"}:
        conda_command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", *conda_command]
    return subprocess.call(conda_command, cwd=PROJECT_ROOT, env=environment)


def _resolve_npm() -> str:
    npm_names = ("npm.cmd", "npm") if os.name == "nt" else ("npm",)
    npm = next((path for name in npm_names if (path := shutil.which(name))), None)
    if npm is None:
        raise LauncherError("npm was not found; install Node.js before starting the frontend.")
    return npm


def _start_process(command: list[str], *, environment: dict[str, str]) -> subprocess.Popen:
    """让前后端继承当前终端输出，但使用独立进程组便于精确清理。"""

    options: dict[str, object] = {
        "cwd": PROJECT_ROOT,
        "env": environment,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    return subprocess.Popen(command, **options)


def _stop_process_tree(process: subprocess.Popen | None) -> None:
    """只终止启动器创建的服务进程树，避免热重载留下孤儿进程。"""

    if process is None or process.poll() is not None:
        return

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except ProcessLookupError:
            return

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=5)


def _backend_command(config: DevConfig) -> list[str]:
    # 不使用 Uvicorn --reload，避免其 Windows CTRL_C_EVENT 波及同终端启动器。
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        config.backend_host,
        "--port",
        str(config.backend_port),
    ]


def _frontend_command(config: DevConfig, npm: str) -> list[str]:
    return [
        npm,
        "--prefix",
        "frontend",
        "run",
        "dev",
        "--",
        "--host",
        config.frontend_host,
        "--port",
        str(config.frontend_port),
    ]


def _wait_for_backend(process: subprocess.Popen, config: DevConfig) -> None:
    """等待 lifespan 和数据库初始化完成后再启动前端。"""

    print(f"[launcher] Waiting for backend health check: {config.backend_health_url}", flush=True)
    deadline = time.monotonic() + config.backend_startup_timeout
    opener = build_opener(ProxyHandler({}))
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise LauncherError(f"Backend exited before becoming ready with code {exit_code}.")
        try:
            with opener.open(config.backend_health_url, timeout=1) as response:
                if response.status == 200:
                    print("[launcher] Backend is ready.", flush=True)
                    return
        except (OSError, TimeoutError, URLError):
            pass
        time.sleep(0.5)
    raise LauncherError(
        f"Backend did not become ready within {config.backend_startup_timeout} seconds."
    )


def _backend_snapshot() -> dict[str, tuple[int, int]]:
    """记录后端源码和 Prompt 的时间戳；缓存、数据库和生成文件不会触发重启。"""

    snapshot: dict[str, tuple[int, int]] = {}
    for path in BACKEND_ROOT.rglob("*"):
        if "__pycache__" in path.parts or not path.is_file():
            continue
        if path.name != ".env" and path.suffix.casefold() not in WATCHED_BACKEND_SUFFIXES:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[path.relative_to(PROJECT_ROOT).as_posix()] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def _changed_paths(
    previous: dict[str, tuple[int, int]],
    current: dict[str, tuple[int, int]],
) -> list[str]:
    return sorted(
        path
        for path in previous.keys() | current.keys()
        if previous.get(path) != current.get(path)
    )


def _format_changed_paths(paths: list[str]) -> str:
    displayed = paths[:5]
    suffix = f" (+{len(paths) - len(displayed)} more)" if len(paths) > len(displayed) else ""
    return ", ".join(displayed) + suffix


def run_dev_services(config: DevConfig) -> int:
    """在同一终端运行两项服务，并分别维护后端重启和前端 Vite HMR。"""

    npm = _resolve_npm()
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    backend: subprocess.Popen | None = None
    frontend: subprocess.Popen | None = None

    try:
        print(f"[launcher] Starting backend: {config.backend_url}", flush=True)
        backend = _start_process(_backend_command(config), environment=environment)
        _wait_for_backend(backend, config)

        print(f"[launcher] Starting frontend: {config.frontend_url}", flush=True)
        frontend = _start_process(_frontend_command(config, npm), environment=environment)
        snapshot = _backend_snapshot()

        print("", flush=True)
        print("[launcher] Comaic development services are running:", flush=True)
        print(f"  Backend : {config.backend_url}", flush=True)
        print(f"  Frontend: {config.frontend_url}", flush=True)
        print("  Backend reload: launcher watcher", flush=True)
        print("  Frontend reload: Vite HMR", flush=True)
        print("Press Ctrl+C to stop both services.", flush=True)

        while True:
            backend_exit = backend.poll()
            if backend_exit is not None:
                print(f"[launcher] Backend exited with code {backend_exit}.", flush=True)
                return backend_exit
            frontend_exit = frontend.poll()
            if frontend_exit is not None:
                print(f"[launcher] Frontend exited with code {frontend_exit}.", flush=True)
                return frontend_exit

            time.sleep(0.5)
            current_snapshot = _backend_snapshot()
            if current_snapshot == snapshot:
                continue

            # 编辑器保存文件时可能连续触发多次变化，短暂等待后合并为一次重启。
            time.sleep(0.25)
            settled_snapshot = _backend_snapshot()
            changed = _changed_paths(snapshot, settled_snapshot)
            print(f"[launcher] Backend changes detected: {_format_changed_paths(changed)}", flush=True)
            print("[launcher] Restarting backend...", flush=True)
            _stop_process_tree(backend)
            backend = _start_process(_backend_command(config), environment=environment)
            _wait_for_backend(backend, config)
            print("[launcher] Backend reload completed.", flush=True)
            snapshot = settled_snapshot
    except KeyboardInterrupt:
        print("\n[launcher] Stop requested.", flush=True)
        return 0
    finally:
        if backend is not None or frontend is not None:
            print("[launcher] Stopping Comaic development services...", flush=True)
        _stop_process_tree(frontend)
        _stop_process_tree(backend)


def main() -> int:
    try:
        env_name = _env_text("CONDA_ENV_NAME", "comaic")
        relaunched_exit_code = _relaunch_in_conda_environment(env_name)
        if relaunched_exit_code is not None:
            return relaunched_exit_code
        return run_dev_services(DevConfig.from_environment())
    except LauncherError as exc:
        print(f"[launcher] {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
