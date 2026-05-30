from pathlib import Path


class PromptLoader:
    """从 prompts/ 目录读取 prompt 模板，避免在 Python 代码里硬编码 prompt。"""

    PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"

    @classmethod
    def load(cls, name: str) -> str:
        """按文件名读取 prompt 文本。"""

        prompt_path = cls.PROMPT_DIR / name
        return prompt_path.read_text(encoding="utf-8")
