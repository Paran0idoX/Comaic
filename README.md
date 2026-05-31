# comaic

基于 LangChain 的 AI 漫画生成 Agent Demo。当前目标是先做 MVP：大纲多轮对话、分页脚本、图片 Prompt、ComfyUI 出图任务和人工选图流程逐步跑通。

## 项目结构

```text
comaic/
├── backend/      # FastAPI + LangChain + SQLAlchemy
├── frontend/     # Vue 3 + Vite + Element Plus
├── data/         # SQLite，本地开发用
├── outputs/      # 生成图片，本地开发用
├── workflows/    # ComfyUI workflow_api.json
├── README.md
├── AGENTS.md
└── .gitignore
```

## 后端

```bash
conda activate lang_graph
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
```

模型配置写在本地 `.env` 中：

```env
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

大纲会话接口：

- `POST /api/outline/sessions`：传入已有 `project_id`，创建大纲会话。
- `POST /api/outline/chat/stream`：使用 SSE 流式返回 `token`，最后返回最新 `outline` 版本。

## 前端

```bash
cd frontend
npm install
npm run dev
```

## 本地数据

- SQLite 默认写入 `data/comaic.sqlite3`
- ComfyUI 生成图片建议写入 `outputs/`
- 真实 `.env`、SQLite 数据库和生成图片不提交到 Git
