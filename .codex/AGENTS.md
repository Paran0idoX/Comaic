# AGENTS.md

本文件是给 Codex 和其他自动化开发代理看的项目说明。修改代码前请先读它，优先遵循这里的项目约定。

## 项目定位

`comaic` 是一个基于 LangChain 的 AI 漫画生成 Agent Demo。MVP 目标是跑通完整链路：

用户输入剧情大纲和总页数 -> 生成每页漫画脚本 -> 生成每页 ComfyUI 文生图 Prompt -> 调用本地 ComfyUI 出候选图 -> 保存项目、页面、图片和任务状态 -> 人工选择每页最终图片。

当前阶段不要做复杂分镜、自动选图、复杂多 Agent 编排或过重架构。优先让链路清晰、可运行、可人工确认。

## 技术栈

- Python
- LangChain / `langchain_core`
- Google Gemini，后续可扩展 OpenAI-compatible LLM
- SQLite
- SQLAlchemy
- ComfyUI API
- `python-dotenv`
- `requests`

## 当前结构

- `main.py`：MVP 入口脚本。适合放 CLI 或最小演示流程。
- `agents/`：Agent 层，只负责 LLM 生成、判断或调用工具。不要直接写复杂数据库逻辑。
- `model_clients/`：模型客户端与环境变量读取，例如 Gemini 客户端。
- `prompts/`：system prompt 和 user prompt 模板。Prompt 不要硬编码在 Python 代码里。
- `tools/`：外部系统封装，例如 `ComfyUIClient`。
- `models/`：SQLAlchemy ORM 实体与数据库初始化。
- `repositories/`：数据库读写逻辑。
- `services/`：业务流程编排，例如创建项目、生成脚本、提交出图任务。
- `workflows/`：ComfyUI `workflow_api.json` 或 workflow 模板。
- `data/`：本地 SQLite 数据库和临时数据。不要提交真实运行数据。
- `api/`：预留的 HTTP API 层，MVP 不强制使用。
- `.codex/`：代理协作说明，不放业务代码。

注意：如果 IDE 中仍显示旧路径，例如 `chains/outline_chain.py`，先以仓库实际文件为准。当前仓库没有 `chains/` 目录。

## 核心数据模型

MVP 核心表位于 `models/comic.py`：

- `comic_project`：项目标题、剧情大纲、Agent 上下文 `thread_id`、时间戳。项目表不保存状态、总页数或 prompt 字段。
- `comic_page`：项目页码、页面脚本、图片 prompt、状态、最终选择图片。
- `comic_image`：页面候选图、远程/本地路径、seed、workflow、prompt、评分、是否选中。
- `generation_task`：ComfyUI prompt id、任务状态、批量大小、错误信息。

数据库初始化入口在 `models/database.py` 的 `init_db()`。默认数据库地址是 `sqlite:///data/comaic.sqlite3`，可用 `.env` 中的 `DATABASE_URL` 覆盖。

## 枚举约定

所有表达固定可选值的字段都使用枚举类，不要在业务代码里散落裸字符串。

- 枚举类统一放在 `models/enums.py`。
- ORM 字段使用 SQLAlchemy `Enum` 类型，并持久化枚举的 `.value`，例如 `draft`、`pending`。
- Repository 和 Service 中更新状态时使用枚举成员，例如 `ComicPageStatus.SCRIPT_READY`，不要写 `"script_ready"`。
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

配置从 `.env` 读取，真实 `.env` 不允许提交到 Git。仓库提供 `.env.example`：

```env
GEMINI_MODEL=gemini-2.5-flash
GEMINI_KEY=your_gemini_api_key

DATABASE_URL=sqlite:///data/comaic.sqlite3
COMFYUI_BASE_URL=http://127.0.0.1:8188
```

约定：

- 不要把真实 API key 写入代码、README、测试快照或日志。
- 不要在回复中复述 `.env` 里的 key。
- 示例配置只能使用占位符。
- 缺少必要环境变量时，错误信息要直接说明缺少什么配置。

## Prompt 约定

- Prompt 文件放在 `prompts/`，优先使用 Markdown。
- 使用 `utils.prompt_loader.PromptLoader` 读取 prompt 内容。
- 命名使用语义化英文，例如 `script_system_prompt.md`、`image_prompt_user_prompt.md`。
- `prompts/ountline_system_prompt.md` 是历史拼写错误文件，仅为兼容保留；新代码使用 `prompts/outline_system_prompt.md`。
- Prompt 模板中使用 `{outline}`、`{total_pages}`、`{script}` 这类显式变量。`total_pages` 可以作为生成脚本时的输入参数，但不存入 `comic_project`。

## MVP 建议流程

1. `ComicService.create_project()` 创建项目记录，不自动创建页面。
2. `ScriptAgent` 读取 `script_system_prompt.md` 和 `script_user_prompt.md`，按页生成脚本。
3. 用户确认或手动修改每页 `script`。
4. `ImagePromptAgent` 读取 `image_prompt_system_prompt.md` 和 `image_prompt_user_prompt.md`，为每页生成英文图片 Prompt。
5. 用户确认或手动修改每页 `image_prompt`。
6. `ComfyUIAgent` 或 service 使用 `tools.ComfyUIClient` 提交 workflow。
7. Repository 保存 `generation_task` 和候选 `comic_image`。
8. 用户调用选择逻辑，设置 `comic_page.selected_image_id` 和 `comic_image.is_selected`。

## OutlineAgent 约定

`agents/outline_agent.py` 负责大纲生成阶段的多轮对话，不负责落库。

- 所有 Agent 优先使用 `langchain.agents.create_agent` 实现；只有明确需要自定义图结构时才直接使用 `StateGraph`。
- 使用 `AsyncSqliteSaver` 保存短期会话记忆，并通过 `create_agent(..., checkpointer=saver)` 传入。当前 LangChain API 参数名是 `checkpointer`。
- 调用时必须传入 `thread_id`，同一个 `thread_id` 会延续同一段大纲讨论。
- Agent 可以返回澄清问题、阶段性大纲草案，或在 `finalize()` 时返回最终大纲文本。
- 用户确认后的保存逻辑放在 Service/Repository 层，通常是把最终大纲传给 `ComicService.create_project(..., thread_id=thread_id)`。
- Prompt 放在 `prompts/outline_conversation_prompt.md` 和 `prompts/outline_finalize_prompt.md`，不要硬编码在 Python 中。

## 开发与验证

安装依赖：

```bash
pip install -r requirements.txt
```

导入与建表检查：

```bash
python -c "from models.database import init_db; init_db(); print('db ready')"
```

Repository 快速检查：

```bash
python - <<'PY'
from models.database import SessionLocal, init_db
from repositories.comic_repository import ComicRepository
from services.comic_service import ComicService

init_db()
with SessionLocal() as session:
    service = ComicService(ComicRepository(session))
    project = service.create_project(title="Demo", outline="少年寻找失落星图。")
    page = ComicRepository(session).create_page(project_id=project.id, page_no=1)
    print(project.id, page.page_no)
PY
```

涉及 Gemini 或 ComfyUI 的验证可能调用网络或本地服务，默认不要在导入测试中触发真实生成请求。

## 安全注意

- `.env` 属于本地敏感配置，不应提交真实内容。
- 避免在异常、print、日志中输出完整 API key。
- 需要展示 key 状态时，只展示是否存在，或最多展示脱敏后的前后几位。
- `data/` 中的真实数据库和生成图片不要提交，除非明确是小型 fixture。
- 网络调用可能产生费用，默认测试应避免实际调用 Gemini。

## 给后续代理的工作建议

1. 先运行 `git status --short`，确认当前工作区是否已有用户改动。
2. 修改前读取相关文件，不要根据文件名猜实现。
3. 保持改动聚焦，避免顺手重构无关模块。
4. 新增依赖要同步更新 `requirements.txt`。
5. 新增 prompt 要放在 `prompts/`，不要硬编码在 Python 里。
6. 完成后至少做一次导入级验证；若无法运行，说明原因。
