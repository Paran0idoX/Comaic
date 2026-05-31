# AGENTS.md

本文件是给 Codex 和其他自动化开发代理看的项目说明。修改代码前请先读它，优先遵循这里的项目约定。

## 项目定位

`comaic` 是一个基于 LangChain 的 AI 漫画生成 Agent Demo。MVP 目标是跑通完整链路：

用户输入剧情大纲和总页数 -> 生成每页漫画脚本 -> 生成每页 ComfyUI 文生图 Prompt -> 调用本地 ComfyUI 出候选图 -> 保存项目、页面、图片和任务状态 -> 人工选择每页最终图片。

当前阶段不要做复杂分镜、自动选图、复杂多 Agent 编排或过重架构。优先让链路清晰、可运行、可人工确认。

## 顶层结构

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

## 后端结构

- `backend/main.py`：FastAPI 入口，当前提供启动建表和 `/health`。
- `backend/agents/`：Agent 层，只负责 LLM 生成、判断或调用工具，不直接写复杂数据库逻辑。
- `backend/model_clients/`：模型客户端与环境变量读取，例如 DeepSeek 客户端。
- `backend/prompts/`：system prompt 和 user prompt 模板，Prompt 不要硬编码在 Python 代码里。
- `backend/tools/`：外部系统封装，例如 `ComfyUIClient`。
- `backend/models/`：SQLAlchemy ORM 实体、枚举与数据库初始化。
- `backend/repositories/`：数据库读写逻辑。
- `backend/services/`：业务流程编排，例如创建项目、生成脚本、提交出图任务。
- `backend/api/`：后续可拆分 FastAPI router。

## 前端结构

- `frontend/` 使用 Vue 3 + Vite + Element Plus。
- 当前只放 MVP 占位工作台，后续接入大纲对话、脚本确认、Prompt 确认和图片选择。
- 前端依赖和脚本写在 `frontend/package.json`。

## 核心数据模型

MVP 核心表位于 `backend/models/comic.py`：

- `comic_project`：项目标题、时间戳。项目表不保存状态、总页数、prompt、大纲或 `thread_id`。
- `session`：通用业务会话，使用 `purpose` 区分大纲等场景，并用 `thread_id` 关联 Agent 记忆。
- `outline_version`：大纲版本快照，归属于具体会话，每个会话只保留最近 5 个版本。
- `comic_page`：项目页码、页面脚本、图片 prompt、状态、最终选择图片。
- `comic_image`：页面候选图、远程/本地路径、seed、workflow、prompt、评分、是否选中。
- `generation_task`：ComfyUI prompt id、任务状态、批量大小、错误信息。

数据库初始化入口在 `backend/models/database.py` 的 `init_db()`。默认数据库地址是 `sqlite:///data/comaic.sqlite3`，从项目根目录运行后端时会写入根目录 `data/`。

## 枚举约定

所有表达固定可选值的字段都使用枚举类，不要在业务代码里散落裸字符串。

- 枚举类统一放在 `backend/models/enums.py`。
- ORM 字段使用 SQLAlchemy `Enum` 类型，并持久化枚举的 `.value`，例如 `draft`、`pending`。
- Repository 和 Service 中更新状态时使用枚举成员，例如 `ComicPageStatus.SCRIPT_READY`。
- 如果后续新增 `status`、`type`、`source`、`provider` 等固定值字段，先新增或复用枚举类，再写数据库字段和业务逻辑。
- 只有自由文本或外部可变名称才继续使用字符串，例如 `workflow_name`。

## 分层原则

- Agent：面向单一智能任务，例如生成分页脚本、生成图片 Prompt、调用 ComfyUI 工具。Agent 不直接操作数据库。
- Service：编排业务流程，例如创建项目、调用 Agent、写入 Repository、更新状态。
- Repository：只处理数据库增删改查，不调用 LLM，也不调用 ComfyUI。
- Tool：封装外部系统调用，例如 ComfyUI HTTP API，不写业务状态流转。
- Model client：集中读取模型相关环境变量，避免业务代码散落 API key 读取逻辑。

保持每层轻量。MVP 中可以先用少量类和函数，不要为了“像框架”而增加复杂抽象。

## 注释约定

- 关键类、方法和不直观的业务流程必须添加中文 docstring 或中文注释。
- 注释解释“为什么这样做”和“这个方法负责什么”，不要逐行复述代码。
- 分层边界、状态流转、外部系统调用、数据库关系、Agent 记忆等位置优先补注释。
- 新增代码保持注释简洁，避免把简单赋值写成噪音注释。

## 环境变量

配置从 `.env` 读取，真实 `.env` 不允许提交到 Git。示例文件位于 `backend/.env.example`：

```env
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=

DATABASE_URL=sqlite:///data/comaic.sqlite3
COMFYUI_BASE_URL=http://127.0.0.1:8188
```

约定：

- 不要把真实 API key 写入代码、README、测试快照或日志。
- 不要在回复中复述 `.env` 里的 key。
- 示例配置只能使用占位符。
- 缺少必要环境变量时，错误信息要直接说明缺少什么配置。

## Prompt 约定

- Prompt 文件放在 `backend/prompts/`，优先使用 Markdown。
- 使用 `backend.utils.prompt_loader.PromptLoader` 读取 prompt 内容。
- 命名使用语义化英文，例如 `script_system_prompt.md`、`image_prompt_user_prompt.md`。
- `backend/prompts/ountline_system_prompt.md` 是历史拼写错误文件，仅为兼容保留；新代码使用 `backend/prompts/outline_system_prompt.md`。
- Prompt 模板中使用 `{outline}`、`{total_pages}`、`{script}` 这类显式变量。`total_pages` 可以作为生成脚本时的输入参数，但不存入 `comic_project`。

## OutlineAgent 约定

`backend/agents/outline_agent.py` 负责大纲生成阶段的主 Agent 对话，不负责落库。

- 所有 Agent 优先使用 `langchain.agents.create_agent` 实现；只有明确需要自定义图结构时才直接使用 `StateGraph`。
- 使用 `AsyncSqliteSaver` 保存短期会话记忆，并通过 `create_agent(..., checkpointer=saver)` 传入。当前 LangChain API 参数名是 `checkpointer`。
- 调用时必须传入 `thread_id`，同一个 `thread_id` 会延续同一段大纲讨论。
- 普通对话方法 `chat()` 使用异步流式输出，调用方用 `async for chunk in agent.chat(...)` 接收文本片段。
- 大纲阶段采用主子 Agent：
  - 主 Agent 负责自然对话、引导用户、判断是否需要更新大纲。
  - 当前大纲作为本轮临时 system context 传给主 Agent，不作为用户消息写入 checkpoint。
  - 主 Agent 可以通过本地 tool 调用子 Agent，但不直接落库。
  - 子 Agent 位于 `backend/agents/outline_update_agent.py`，只负责根据当前大纲和用户输入生成新的大纲文本。
  - 子 Agent 不使用普通对话 checkpoint，不保存数据库。
- 大纲版本保存逻辑放在 Service/Repository/API 层；只有主 Agent 调用子 Agent 并产出新大纲时，才保存为新的 `outline_version`。
- Prompt 放在 `backend/prompts/outline_conversation_prompt.md`、`backend/prompts/outline_update_prompt.md`、`backend/prompts/outline_finalize_prompt.md` 和 `backend/prompts/outline_snapshot_prompt.md`，不要硬编码在 Python 中。

## 开发与验证

后端安装依赖：

```bash
conda activate lang_graph
pip install -r backend/requirements.txt
```

后端启动：

```bash
uvicorn backend.main:app --reload
```

导入与建表检查：

```bash
python -c "from backend.models.database import init_db; init_db(); print('db ready')"
```

Repository 快速检查：

```bash
python - <<'PY'
from backend.models.database import SessionLocal, init_db
from backend.repositories.comic_repository import ComicRepository
from backend.services.comic_service import ComicService

init_db()
with SessionLocal() as session:
    repo = ComicRepository(session)
    service = ComicService(repo)
    project = service.create_project(title="Demo")
    outline_session = service.create_outline_session(project_id=project.id)
    page = repo.create_page(project_id=project.id, page_no=1)
    print(project.id, outline_session.thread_id, page.page_no)
PY
```

前端安装和启动：

```bash
cd frontend
npm install
npm run dev
```

涉及 DeepSeek、ComfyUI 或 npm/pip 安装的验证可能调用网络或本地服务，默认不要在导入测试中触发真实生成请求。

## 安全注意

- `.env` 属于本地敏感配置，不应提交真实内容。
- 避免在异常、print、日志中输出完整 API key。
- 需要展示 key 状态时，只展示是否存在，或最多展示脱敏后的前后几位。
- `data/` 中的真实数据库、`outputs/` 中的生成图片不要提交，除非明确是小型 fixture。
- 网络调用可能产生费用，默认测试应避免实际调用 DeepSeek。

## 给后续代理的工作建议

1. 先运行 `git status --short`，确认当前工作区是否已有用户改动。
2. 修改前读取相关文件，不要根据文件名猜实现。
3. 保持改动聚焦，避免顺手重构无关模块。
4. 新增后端依赖要同步更新 `backend/requirements.txt`；新增前端依赖要同步更新 `frontend/package.json`。
5. 新增 prompt 要放在 `backend/prompts/`，不要硬编码在 Python 里。
6. 完成后至少做一次导入级验证；若无法运行，说明原因。
