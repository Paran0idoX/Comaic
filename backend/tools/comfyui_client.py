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

    def get_queue(self) -> dict[str, Any]:
        """读取 ComfyUI 当前队列；主要用于排障和后续扩展。"""

        response = requests.get(f"{self.base_url}/queue", timeout=30)
        response.raise_for_status()
        return response.json()

    def download_view_image(
        self,
        *,
        filename: str,
        subfolder: str = "",
        image_type: str = "output",
    ) -> bytes:
        """通过 /view 下载 ComfyUI 生成的图片二进制内容。"""

        response = requests.get(
            f"{self.base_url}/view",
            params={
                "filename": filename,
                "subfolder": subfolder,
                "type": image_type,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.content

    @staticmethod
    def extract_output_images(history: dict[str, Any], prompt_id: str) -> list[dict[str, str]]:
        """从 /history 响应中提取图片文件描述，兼容 ComfyUI 标准输出结构。"""

        prompt_history = history.get(prompt_id, history)
        outputs = prompt_history.get("outputs", {}) if isinstance(prompt_history, dict) else {}
        images: list[dict[str, str]] = []
        for node_output in outputs.values():
            if not isinstance(node_output, dict):
                continue
            for image in node_output.get("images", []):
                if not isinstance(image, dict):
                    continue
                filename = image.get("filename")
                if not filename:
                    continue
                images.append(
                    {
                        "filename": str(filename),
                        "subfolder": str(image.get("subfolder") or ""),
                        "type": str(image.get("type") or "output"),
                    }
                )
        return images
