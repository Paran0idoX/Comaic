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

    def free_memory(self, *, unload_models: bool = True) -> dict[str, Any]:
        """在队列空闲后释放 ComfyUI 模型与缓存，给本机评估进程腾出显存。"""

        response = requests.post(
            f"{self.base_url}/api/free",
            json={"unload_models": unload_models, "free_memory": True},
            timeout=60,
        )
        response.raise_for_status()
        if not response.content:
            return {}
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def queue_is_idle(payload: dict[str, Any]) -> bool:
        """兼容 ComfyUI 标准 queue_running / queue_pending 响应。"""

        return not payload.get("queue_running") and not payload.get("queue_pending")

    @staticmethod
    def queued_prompt_ids(payload: dict[str, Any]) -> set[str]:
        """严格读取队列中的请求 ID；异常响应不能被解释成队列空闲。"""

        result: set[str] = set()
        for key in ("queue_running", "queue_pending"):
            entries = payload.get(key) if isinstance(payload, dict) else None
            if not isinstance(entries, list):
                raise ValueError("ComfyUI queue response is incomplete.")
            for entry in entries:
                if (
                    not isinstance(entry, (list, tuple)) or len(entry) < 2
                    or not isinstance(entry[1], str) or not entry[1]
                ):
                    raise ValueError("ComfyUI queue entry is invalid.")
                result.add(str(entry[1]))
        return result

    def upload_image(
        self,
        *,
        content: bytes,
        filename: str,
        subfolder: str = "comaic",
        overwrite: bool = False,
    ) -> str:
        """上传参考图/控制图，并返回可注入 LoadImage 节点的稳定名称。"""

        response = requests.post(
            f"{self.base_url}/upload/image",
            files={"image": (filename, content, "application/octet-stream")},
            data={
                "subfolder": subfolder,
                "overwrite": "true" if overwrite else "false",
                "type": "input",
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        uploaded_name = payload.get("name")
        uploaded_subfolder = str(payload.get("subfolder") or subfolder).strip("/")
        if not uploaded_name:
            raise ValueError(f"ComfyUI upload response missing name: {payload}")
        return f"{uploaded_subfolder}/{uploaded_name}" if uploaded_subfolder else str(uploaded_name)

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

    @staticmethod
    def extract_execution_error(history: dict[str, Any], prompt_id: str) -> str | None:
        """从 history 的状态消息中提取执行错误，避免无图片时无限轮询。"""

        prompt_history = history.get(prompt_id, history)
        if not isinstance(prompt_history, dict):
            return None
        status = prompt_history.get("status")
        if not isinstance(status, dict):
            return None
        messages = status.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                if not isinstance(message, (list, tuple)) or len(message) < 2:
                    continue
                kind = str(message[0])
                if kind not in {"execution_error", "execution_interrupted"}:
                    continue
                details = message[1] if isinstance(message[1], dict) else {}
                parts = [
                    str(details.get("exception_type") or kind),
                    str(details.get("exception_message") or "").strip(),
                    (
                        f"node {details.get('node_id')} ({details.get('node_type')})"
                        if details.get("node_id") or details.get("node_type")
                        else ""
                    ),
                ]
                return ": ".join(value for value in parts if value)[:2000]
        status_text = str(status.get("status_str") or "").lower()
        if status_text in {"error", "failed", "failure"}:
            return f"ComfyUI history status is {status_text}."
        return None
