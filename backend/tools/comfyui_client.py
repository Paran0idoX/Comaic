from typing import Any

import requests


class ComfyUIClient:
    """ComfyUI HTTP API 的轻量封装。"""

    def __init__(self, base_url: str = "http://127.0.0.1:8188"):
        """保存 ComfyUI 服务地址，并移除末尾斜杠避免拼接 URL 出错。"""

        self.base_url = base_url.rstrip("/")

    def queue_prompt(self, workflow: dict[str, Any]) -> str:
        """提交 workflow 到 ComfyUI 队列，并返回 ComfyUI 的 prompt_id。"""

        response = requests.post(
            f"{self.base_url}/prompt",
            json={"prompt": workflow},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        prompt_id = payload.get("prompt_id")
        if not prompt_id:
            raise ValueError(f"ComfyUI response missing prompt_id: {payload}")
        return prompt_id

    def get_history(self, prompt_id: str) -> dict[str, Any]:
        """根据 prompt_id 查询 ComfyUI 任务历史和结果。"""

        response = requests.get(f"{self.base_url}/history/{prompt_id}", timeout=30)
        response.raise_for_status()
        return response.json()
