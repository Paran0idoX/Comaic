from pathlib import Path


class PromptLoader:
    """从 prompts/ 目录读取 prompt 模板，避免在 Python 代码里硬编码 prompt。"""

    PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"

    @classmethod
    def load(cls, name: str) -> str:
        """按文件名读取 prompt 文本。"""

        prompt_path = cls.PROMPT_DIR / name
        return prompt_path.read_text(encoding="utf-8")

    @classmethod
    def load_system(cls, name: str, *, fallback: str | None = None) -> str:
        """新建 Agent 时读取设置覆盖；普通模板和业务协议仍只读 Markdown。"""
        from sqlalchemy.exc import OperationalError
        from backend.models.database import SessionLocal
        from backend.repositories.comic_repository import ComicRepository
        from backend.utils.system_prompt_catalog import SYSTEM_PROMPT_FILES

        key = next((key for key, filename in SYSTEM_PROMPT_FILES.items() if filename == name), None)
        if key is not None:
            try:
                with SessionLocal() as session:
                    content = ComicRepository(session).get_system_prompt_content(key, fallback=fallback)
                if content is not None:
                    return content
            except OperationalError as exc:
                # 离线 Agent 单测可以没有应用库；启动后迁移会补齐字段，其它数据库错误正常抛出。
                if not any(value in str(exc.orig) for value in ("no such table", "no such column")):
                    raise
        return fallback if fallback is not None else cls.load(name)
