# AGENTS.md

本文件是给 Codex 和其他自动化开发代理看的项目说明。修改代码前请先读它，优先遵循这里的项目约定。

## 项目定位

`comaic` 是一个基于 LangChain 的 AI 漫画生成 Agent Demo。MVP 目标是跑通完整链路：

用户输入剧情大纲和总页数 -> 生成每页漫画脚本 -> 维护已确认的画面设定与独立参考原图 -> 为每页编译三类 ImageSpec -> 调用所选生图 Provider -> 保存项目、页面、图片和任务状态 -> 人工选择每页最终图片。

当前阶段不要做复杂分镜、自动选择最终候选图、复杂多 Agent 编排或过重架构。参考原图按本页 ShotPlan 和确定规则自动选择，最终候选图仍由用户选择。优先让链路清晰、可运行、可人工确认。

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
- `backend/llm_clients/`：LLM 客户端工厂，运行时优先读取 SQLite 中的 OpenAI 兼容模型配置。
- `backend/prompts/`：system prompt 和 user prompt 模板，Prompt 不要硬编码在 Python 代码里。
- `backend/tools/`：外部系统封装，例如 `ComfyUIClient`。
- `backend/models/`：SQLAlchemy ORM 实体、枚举与数据库初始化。
- `backend/repositories/`：数据库读写逻辑。
- `backend/services/`：业务流程编排，例如创建项目、生成脚本、提交出图任务。
- `backend/api/`：后续可拆分 FastAPI router。

## 前端结构

- `frontend/` 使用 Vue 3 + Vite + Element Plus。
- 当前包含故事大纲、分页脚本、画面设定、生图准备、漫画出图和设置等 MVP 工作台；历史文件、路由及数据库命名保持兼容。
- 前端依赖和脚本写在 `frontend/package.json`。
- 前端功能如果需要额外 npm 包，可以安装轻量、明确用途的依赖；安装后必须同步更新 `frontend/package.json` 和 `frontend/package-lock.json`，并在完成后运行前端类型检查或构建。
- LLM 生成的大纲、脚本等富文本内容如果按 Markdown 展示，优先使用成熟 Markdown 渲染库；默认关闭原始 HTML 解析，避免把模型输出当成可执行 HTML。

## 核心数据模型

MVP 核心表位于 `backend/models/comic.py`：

- `comic_project`：项目标题、时间戳。项目表不保存状态、总页数、prompt、大纲或 `thread_id`。
- `session`：通用业务会话，使用 `purpose` 区分大纲等场景，并用 `thread_id` 关联 Agent 记忆。
- `outline_version`：大纲版本快照，归属于具体会话，每个会话只保留最近 5 个版本。
- `comic_page`：项目页码、结构化页面脚本、状态、最终选择图片。页面不保存单个 `script` 或 `image_prompt` 字段，脚本使用 `summary`、`characters`、`clothing`、`scene`、`composition`、`character_action`、`dialogue` 等字段表达。
- `image_spec`：页面在某次视觉编译下的模型无关生图规格，每页分别保存 `tag`、`natural_language`、`hybrid` 三种 Prompt 表达。
- `comic_image`：页面生成图片、远程/本地路径、seed、workflow、prompt、评分、是否选中。
- `generation_task` / `generation_run`：批量任务状态与逐候选的 Provider、Prompt 类型、ImageSpec 溯源和外部请求 id。
- `image_generation_tool_preset`：生图 Provider 配置；ComfyUI 保存 workflow/binding，OpenAI Images 兼容工具保存其接口配置。
- `llm_config`：LangChain Provider 模型配置；单表保存多组 API 配置，每组用 `model_names` JSON 字段维护多个模型名，并用 `default_model` 指定该组默认模型。API Key 只保存在本地 SQLite，设置页会按本地 MVP 需求明文回显。

数据库初始化入口在 `backend/models/database.py` 的 `init_db()`。默认数据库地址是 `sqlite:///data/comaic.sqlite3`，从项目根目录运行后端时会写入根目录 `data/`。

## 枚举约定

所有表达固定可选值的字段都使用枚举类，不要在业务代码里散落裸字符串。

- 枚举类统一放在 `backend/models/enums.py`。
- ORM 字段使用 SQLAlchemy `Enum` 类型，并持久化枚举的 `.value`，例如 `draft`、`pending`。
- Repository 和 Service 中更新状态时使用枚举成员，例如 `ComicPageStatus.SCRIPT_READY`。
- 如果后续新增 `status`、`type`、`source`、`provider` 等固定值字段，先新增或复用枚举类，再写数据库字段和业务逻辑。
- 只有自由文本或外部可变名称才继续使用字符串，例如 `workflow_name`。

## 分层原则

- Agent：面向单一智能任务，例如生成分页脚本或规划 ShotPlan。Agent 不直接操作数据库。
- Service：编排业务流程，例如创建项目、调用 Agent、写入 Repository、更新状态。
- Repository：只处理数据库增删改查，不调用 LLM，也不调用 ComfyUI。
- Tool：封装外部系统调用，例如 ComfyUI HTTP API，不写业务状态流转。
- Model client：集中读取模型配置，避免业务代码散落 API key 读取逻辑。
  - 新代码通过 `backend/llm_clients/factory.py` 创建模型实例，不直接读取 `.env` 或缓存模块级全局模型。
  - 模型配置优先来自 active `llm_config` 的 `default_model`；没有配置时才用 `.env` 初始化默认 API 组和模型名列表。
  - 设置页修改模型配置后，只影响后续新建的 Agent/LLM 调用，不强制切换正在运行的长任务。
  - 默认按 Provider 显式创建对应 LangChain Chat 类，例如 `ChatDeepSeek`、`ChatAnthropic`；只有用户选择 `openai_compatible` 时才用 `ChatOpenAI(base_url=...)`。
  - `create_chat_model()` 支持 `thinking_enabled` 入参；当前只对 `LLMProvider.DEEPSEEK` 下发思考模式开关。
  - DeepSeek 不再有结构化输出 JSON object 特判，和其它 Provider 一样走标准 LangChain `response_format`。
- 使用 `response_format` 的 Agent 必须优先复用 `backend/agents/structured_output.py` 中的 `ainvoke_structured_with_retries()`。
  - 只读取 `structured_response`，不要从自然语言、Markdown 代码块或文件输出中兜底解析 JSON。
  - Agent 自己通过 `validator` 传入业务级结构校验，例如页面列表非空、Prompt 非空。
- 结构化输出重试只解决模型输出形态问题；页码范围、字段完整性、落库状态流转仍放在 Service/Repository 层。

保持每层轻量。MVP 中可以先用少量类和函数，不要为了“像框架”而增加复杂抽象。

## 长任务心跳约定

- `script_generation_task` 和 `generation_task` 使用 `heartbeat_at` 记录当前运行心跳。
- `backend/services/task_runtime.py` 维护进程内运行中任务注册表，并在 FastAPI lifespan 启动两个后台线程：心跳线程和僵尸任务扫描线程。
- Service 在任务进入 `running` 后必须注册到 `running_task_registry`，在任务完成、失败、暂停或 generator 退出时必须注销。
- 心跳线程只刷新注册表中的任务，不能直接刷新数据库中所有 `running` 任务，否则应用重启后的僵尸任务会被误续命。
- 僵尸扫描只把心跳超时的 `running` 任务改为 `suspended`，不自动恢复；恢复仍走现有继续生成入口。

## 注释约定

- 关键类、方法和不直观的业务流程必须添加中文 docstring 或中文注释。
- 注释解释“为什么这样做”和“这个方法负责什么”，不要逐行复述代码。
- 分层边界、状态流转、外部系统调用、数据库关系、Agent 记忆等位置优先补注释。
- 新增代码保持注释简洁，避免把简单赋值写成噪音注释。

## 环境变量

配置从 `.env` 读取，真实 `.env` 不允许提交到 Git。示例文件位于 `backend/.env.example`：

```env
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

DATABASE_URL=sqlite:///data/comaic.sqlite3
COMFYUI_BASE_URL=http://127.0.0.1:8188
```

约定：

- 不要把真实 API key 写入代码、README、测试快照或日志。
- 不要在回复中复述 `.env` 里的 key。
- 示例配置只能使用占位符。
- `.env` 中的模型名配置只作为首次初始化设置页配置的默认值；API Key 不从环境变量读取，必须通过设置页保存到 SQLite。
- 缺少模型 API Key 不应阻塞后端启动，但实际模型调用或测试连接要返回明确错误。

## Prompt 约定

- Prompt 文件放在 `backend/prompts/`，优先使用 Markdown。
- 使用 `backend.utils.prompt_loader.PromptLoader` 读取 prompt 内容。可维护任务 SystemPrompt 通过 `load_system()` 读取 SQLite 覆盖，协议及普通模板仍用 `load()`；白名单位于 `backend/utils/system_prompt_catalog.py`。
- 模型全局提示词按 API 组和模型名独立保存，由通用 `GlobalSystemPromptMixin` 在请求边界与任务系统消息组合一次，不写入 checkpoint。默认模板关联是配置数据，不在注入层按 Provider/模型名定制。覆盖清空恢复 Markdown 默认，空全局文本关闭注入；新调用创建时冻结配置。
- 命名使用语义化英文，例如 `script_system_prompt.md`、`shot_planner_prompt.md`。
- `backend/prompts/ountline_system_prompt.md` 是历史拼写错误文件，仅为兼容保留；新代码使用 `backend/prompts/outline_system_prompt.md`。
- Prompt 模板中使用 `{outline}`、`{total_pages}`、`{script}` 这类显式变量。`total_pages` 可以作为生成脚本时的输入参数，但不存入 `comic_project`。

## 文案国际化约定

- 前端 UI 文案、进度时间线文案优先放在 `frontend/src/i18n/messages.ts`，通过 vue-i18n 展示。
- 后端返回给前端的业务错误必须使用稳定 `code`，响应结构为 `{"code": "...", "message": "..."}`，不要让前端解析英文错误字符串。
- 后端用户可见文案集中放在 `backend/i18n/`，使用 Python Babel/gettext catalog 管理；运行时可回退到内置中英文表。
- API 层使用 `backend.i18n.errors.http_exception()` 和 `sse_error_payload()` 统一转换异常；Service/Repository 可以继续抛业务异常，但不要直接把原始外部错误作为用户主文案暴露。
- Agent 输出、用户输入、Prompt 文件、日志和代码注释不纳入普通 UI 国际化。

Babel catalog 维护命令：

```bash
pybabel extract -F backend/babel.cfg -o backend/locales/messages.pot backend
pybabel update -i backend/locales/messages.pot -d backend/locales
pybabel compile -d backend/locales
```

## OutlineAgent 约定

`backend/agents/outline_agent.py` 负责大纲生成阶段的主 Agent 对话，不负责落库。

- 所有 Agent 优先使用 `langchain.agents.create_agent` 实现；只有明确需要自定义图结构时才直接使用 `StateGraph`。
- 使用 `AsyncSqliteSaver` 保存短期会话记忆，并通过 `create_agent(..., checkpointer=saver)` 传入。当前 LangChain API 参数名是 `checkpointer`。
- 调用时必须传入 `thread_id`，同一个 `thread_id` 会延续同一段大纲讨论。
- 普通对话方法 `chat()` 使用异步流式输出，调用方用 `async for chunk in agent.chat(...)` 接收文本片段。
- 大纲阶段采用主子 Agent：
  - 主 Agent 负责自然对话、引导用户、判断是否需要更新大纲。
  - 大纲主 Agent 和大纲更新子 Agent 默认使用当前 active 模型配置。
  - 当前大纲作为本轮临时 system context 传给主 Agent，不作为用户消息写入 checkpoint。
  - 主 Agent 可以通过本地 tool 调用子 Agent，但不直接落库。
  - 子 Agent 位于 `backend/agents/outline_update_agent.py`，只负责根据当前大纲和用户输入生成新的大纲文本。
  - 子 Agent 不使用普通对话 checkpoint，不保存数据库。
- 大纲版本保存逻辑放在 Service/Repository/API 层；只有主 Agent 调用子 Agent 并产出新大纲时，才保存为新的 `outline_version`。
- `OutlineCharacterAgent` 在同一次结构化调用中分类角色、道具、场景和抽象设定；只有具有独立身份与形象的故事参与者进入角色基准表，动物、机器人和拟人角色同样允许。历史角色必须重新判断，不能仅凭已有 key 保留。
- 新大纲必须在角色分类和设定校验通过后，才与合法角色一起落库；提取重试耗尽使用 `outline.characters_invalid`，不得切换活动版本或修改历史角色。分类信息只用于 Agent，不进入数据库或公开 API。
- Prompt 放在 `backend/prompts/outline_conversation_prompt.md`、`backend/prompts/outline_update_prompt.md`、`backend/prompts/outline_finalize_prompt.md` 和 `backend/prompts/outline_snapshot_prompt.md`，不要硬编码在 Python 中。

## ScriptPlanningAgent / PageScriptWriterAgent / ScriptSupervisorAgent 约定

`backend/agents/script_planning_agent.py` 负责分页脚本的故事节奏分段规划、中心化场景设定和分段角色细化设定，不负责落库。
`backend/agents/page_script_writer_agent.py` 负责基于已锁定分段和视觉设定生成分页漫画脚本，不负责落库。
`backend/agents/script_supervisor_agent.py` 负责审查分页脚本并提供逐页修改意见，不负责落库。

- 分页脚本不再使用 `ScriptDeepAgent` 或 DeepAgents 主子 Agent 编排；Service 显式编排 Planning、Writer 和 Supervisor。
- 分段规划 Agent 输出 `section_plan`，并且每个 section 必须包含该段涉及的 `scenes` 和 `characters`。
- 新分段规划还必须包含逐页 `page_plan`（`page_no`、`scene_key`、`beat`）；Service 在锁定前校验页码完整性和本段场景引用，Writer/Supervisor 共用已保存的逐页落点。历史规划没有此字段时保持兼容。
- 每页是同一空间、同一瞬间的完整画面；允许动作和多人同时动作，不允许先后动作或混用动作前后的状态。正常左右站位、景别、迈步动势和已经形成的结果状态不属于违规。
- 版本 2 场景的禁止项仅约束固定地点身份；旧目录中禁止人物、天气、光照和临时物品等固定定义范围说明，不作为本页画面禁令。四项 `scene_conditions` 可分别为空。Supervisor 只退回明确阻断画面、真实固定设定或核心剧情的错误，文字优化不触发重试。
- 分段计划必须由 Service 校验并落库锁定后，才能进入页面脚本生成阶段。
- 分页脚本 Agent 默认使用当前 active 模型配置。
- PageScriptWriterAgent 只能引用当前 section 已锁定的 `scene_key` 和 `character_key`，不能新增或改写视觉设定。
- ScriptSupervisorAgent 只输出 `passed/reviews`，reviews 必须按单页给出修改意见。
- 批量脚本生成由 Service 遍历已锁定分段，逐段调用 Writer 和 Supervisor；Agent 不能自行选择或回退到其他分段。
- 当前分段脚本必须先由 Service 校验页码完整性、连续性、字段完整性和视觉设定引用，再通过 Supervisor 审查。
- Supervisor 给出修改意见时，Service 通过 SSE 发送 `review` 事件，并把意见反馈给 Writer 重试当前 section。
- 当前 section 校验和审查通过后，Service 逐页落库并逐页发送 `page` SSE，最后发送 `section_pages` 兜底同步。
- 单页生成可以跳过整体节奏划分，但仍要经过监督审查。
- 批量生成通过 SSE 暴露长任务进度，脚本任务状态保存到 `script_generation_task`。
- 前端分页脚本页依赖 Vue `KeepAlive` 保持长 SSE 连接和内存进度；不要随意移除 `ScriptWorkspaceView` 的缓存，否则路由切换会中断前端对生成进度的消费。
- 分页脚本结果保存到 `comic_page` 的结构化字段：`summary`、`characters`、`clothing`、`scene`、`composition`、`character_action`、`dialogue`，页面状态使用 `ComicPageStatus.SCRIPT_READY`。
- 角色一致性分两层：
  - 大纲阶段生成并确认 `outline_character` 角色基准设定，保存名称、身份、背景、固定样貌和禁止改写项。
  - 大纲角色里的默认发型、默认服装、默认配件、默认色彩只作为脚本阶段的默认值，不是永久锁死项。
  - 脚本阶段按 `script_section` 生成分段角色细化设定，保存当前分段的发型、服装、配件、状态、情绪和临时变化。
- 分页脚本生成需要同步产出分段级视觉设定：
  - 新 `script_scene` 只保存固定地点：名称、地点类型、建筑、布局、材质、固定陈设、固有颜色和固定禁止项。名称和 `scene_key` 不含时段、天气、光照或氛围，同一地点跨分段复用同一个 key。
  - Planning 只接收项目中版本 2 的固定场景目录；复用必须返回准确的 `reference_subject_key`，由 Service 校验绑定，新地点由 Service 创建，不能通过模糊名称合并。单页生成也先用同一 Planning Agent 规划目标页的场景和角色。
  - `script_character` 归属于 `script_section`，`character_key` 在同一分段内唯一，并通过 `outline_character_id` 回溯到大纲角色基准。
  - `comic_page.scene_id` 和 `comic_page_character` 负责把页面绑定到具体场景和角色。
  - 页面自己的 `scene`、`characters`、`clothing` 只描述本页局部变化，不承担全局一致性职责。
  - `comic_page.scene_conditions_json` 可空，Writer 逐页输出 `{time_of_day, weather, lighting, atmosphere}` 自由文本，空字符串表示未指定。固定场景与本页条件分别进入上下文，三类 Prompt 都消费页面条件，Supervisor 检查与本页文字的一致性，不要求同地点条件恒定。
  - HTTP 和 SSE 共用关联名称、场景条目 ID/名称、`character_bindings` 和 `scene_conditions`。列表展示关联名称，详情展示人物基准、分段造型、场景条目与本页条件。
  - 人工编辑仅允许当前分段人物和当前批次场景，关联、条件与文本在同一事务保存，不自动改写文本，保存后待审查。省略字段保留原值，`character_ids=[]` 表示无人物，场景不能主动清空，新建页面必须选场景；复审读取页面实际绑定场景，自动 Writer 仍限于原分段场景。
  - 脚本任务和目录条目使用 `scene_definition_version`：迁移旧记录为 1，业务新建为 2。旧日夜场景、版本、图片和未完成任务保留兼容，不自动合并；历史页面未记录条件时读取原场景，人工保存后只覆盖本页。
- Service 保存脚本视觉设定时，会自动派生画面设定草稿：
  - 分段角色的当前服装、配件和大纲默认色彩生成 `OutfitVariant(DRAFT)`；相同角色的相同造型按内容 key 复用。
  - 新固定场景的空间和固有色彩生成 `SceneVisualVersion(DRAFT)`，新版本不保存光照或临时物件状态；历史版本保留旧条件。重试和继续生成不得重复创建相同内容。
  - 自动草稿可以绑定到 `script_character` / `script_scene` 供前端审核，但只有 `APPROVED` 版本才能进入 Final ImageSpec。
  - 已有人工绑定不得被自动派生覆盖；无法回溯到 `outline_character` 的分段角色不自动创建服装版本。
  - 从具体分段角色或场景编辑时，“保存并应用”在同一事务内新增已确认版本并绑定明确目标；校验编辑时的原绑定，冲突则整体回滚。素材库复制和“仅存草稿”不修改绑定，不自动应用到其它分段。
  - 参考图片通过画面设定页按类别生成或上传、预览和人工确认。历史画风配置保留审计，新准备不再消费画风。
- 脚本 Agent prompt 放在 `backend/prompts/script_planning_prompt.md`、`script_writer_prompt.md` 和 `script_supervisor_prompt.md`。

## ImageSpec / Prompt 类型约定

`backend/services/image_spec_service.py` 负责把本页绑定的角色基准、当前造型、场景设定、页面脚本和 ShotPlan 编译成模型无关的 ImageSpec；这条链路不再使用 ImagePromptAgent，也不再向 `comic_page` 写单一 `image_prompt`。

- Prompt 表达只分为 `tag`、`natural_language`、`hybrid` 三类，统一使用 `ImagePromptType`，不得引入具体图片模型、checkpoint 或模型家族作为业务分支。
- 每次按脚本任务编译时，每页必须共享同一个 ShotPlan，并分别生成三条 ImageSpec；同一页、同一 Prompt 类型只保留一条当前有效规格。
- Hybrid 必须同时保存 tag 与自然语言组件；最终正向/负向 Prompt 的组合顺序都是“自然语言 + 换行 + tag”。
- 历史风格字段、记录和快照保留；新编译不应用 `style_profile_id` 或风格参考图，也不让历史画风改动影响新准备的来源 Hash。
- Negative Prompt preset 分别维护 tag 与自然语言内容；ShotPlanner preset 与 Negative Prompt preset 统一由生图准备页面管理。
- ImageSpec 必须组合大纲级 `outline_character`、分段级 `script_character`、任务级 `script_scene`、已批准视觉资产和单页结构化脚本。
- 固定场景与本页条件分别组织；关联和条件变化进入逐页来源 Hash，仅让受影响页的准备过期并取消旧最终选择，候选图保留。冻结批次继续使用原快照。
- 新生图准备按页直接构建确定性上下文，不调用跨页事件提取 Agent，不重放连续性状态机。角色固定外貌与当前造型复用绑定设定；动作、表情、湿衣或破损等本页变化由页面脚本表达，不从前页推演。
- `ContinuityCompilation` / `VisualStateSnapshot` 历史表名与外键保留兼容；新记录只保存按页上下文快照和空事件列表，旧事件与状态快照仅供历史审计。新来源 Hash 使用独立版本，未开始的旧规格需要重新准备；已冻结生图批次继续沿用原 Prompt、参考输入和 seed。
- 三种 ImageSpec 都成功后，页面状态才更新为 `ComicPageStatus.SPEC_READY`。
- 提示词只在生图准备中显式生成和选择输出语言。漫画出图只消费已有提示词，不调用模型自动补齐、转换语言或重新准备；缺少或过期时在任何上传和提交前拒绝，并提示返回生图准备。准备时逐页比较实时上下文 Hash，按相同页面输入复用 ShotPlan 和规格；整批 Hash 仅用于历史审计。
- 历史 LoRA 资产只保留归档审计；新业务不创建、不提升、不绑定 LoRA。底模、LoRA、采样器等具体实现由 ComfyUI workflow 自行管理。

## 参考原图与按页选择约定

- 保存独立原图，不生成拼板。内置人物、场景、物品三类；人物用途为脸部、全身、侧面和背面；半身用途仅保留历史数据读取，不再生成、上传或选用。分类在代码中集中声明，可扩展，但不增加用户自定义分类管理。
- 人物归属 `OutlineCharacter`，身体图可用 `outfit_variant_id` 标注当前造型；场景和物品用 `ReferenceSubject` 目录，`ScriptScene.reference_subject_id` 显式绑定目录场景。历史场景资产的 `entity_id` 仍指向 `SceneVisualVersion`，不能重解释为目录 ID。
- 新场景参考图直接归属版本 2 场景条目，`entity_id` 必须为 NULL；上传、单次生成、批量生成和快速选图取消“适用场景”版本选择。生成只读取固定建筑、布局、材质、陈设与固有颜色，不读取页面条件或场景版本；以清楚展示结构和材质为目标。历史条目继续支持通用图及版本专用图，以下版本范围及优先级规则仅适用于历史场景。
- 参考图确认采用互斥选择：同一项目、对象、用途及适用范围最多一张已确认图。确认新图时，同槽旧图在同一事务中退回 `DRAFT` 候选，不删除、不归档；再次确认旧生成图复用已有素材，不重复转存。人物脸部按人物与用途互斥，身体图还区分造型；场景通用范围与各版本专用范围独立；物品按目录对象互斥。`promoted_asset_id` 只表达转存关联，候选是否已确认必须读取关联素材当前状态。
- ShotPlanner 只输出人物 `reference_view` / `reference_framing` / `visible_prop_keys` 和场景 `background_visible` / `visible_prop_keys`，不挑 asset_id，不增加逐图视觉 AI。可见物品 key 必须属于输入目录；不入镜的持有物不自动选图。
- `ReferenceSelectionService` 按用途顺序回退：脸部 `[脸,全身]`；半身镜头和全身/未知 `[全身,脸]`；侧面 `[侧面,全身,脸]`；背面 `[背面,全身,侧面,脸]`。半身仍是 ShotPlan 的镜头范围，不再对应独立参考图用途。先匹配类别，再取最新确认版本。明确属于不同造型的身体图排除；未标造型的身体图仅作身份/视角参考，不能覆盖本页确认服装。
- 每个人物最多主图加一张辅助图，背面镜头不加脸部辅助。先按 ShotPlan `depth_order`、`character_key` 排列所有人物主图，再人物辅助、入镜场景和按 key 排列的可见物品。选用场景版本的图片优先于目录场景通用图片；通用图的 `entity_id` 必须为 NULL，版本专用图必须匹配当前选用版本，且 `reference_subject_id` 为 NULL 旧数据或当前绑定条目 ID。重新绑定条目后不能使用旧条目的版本专用图。
- 每页三种 Prompt 共用一份 `reference_plan`，记录 asset_id/version、原图 metadata、owner、purpose、reason/reason_code、priority、is_primary/is_required，以及 omitted/fallbacks/warnings。中文界面用稳定 reason_code 翻译；Provider 用自然语言 reason 解释归属和用途。
- 不提供普通/严格模式选择。参考图是可选增强，缺少人物、入镜场景或可见物品参考时提示并保留文字生成；不要求独立服装图、四类人物图齐备或独立画风条件。
- 实际传入的原图必须可读且 SHA256 未变；无效文件、工作流 binding 和传输配置在任何上传或提交前拦截。工具容量不足时按现有优先级裁减并说明省略项。
- 素材确认/撤回/版本及归属、造型关联、目录绑定与 metadata 变化进入来源 Hash，使未开始的旧准备过期。人脸一致性评测排除背面，保留可检测到脸的脸部、全身和侧面候选，半身历史参考图不再作为新评测输入。

## 图片生成 Provider 约定

`backend/services/image_generation_service.py` 负责图片生成业务编排，`backend/tools/comfyui_client.py` 只封装 ComfyUI HTTP API。

- 生图工具只按 Provider 分类：`comfyui` 与 `openai_images_compatible`；使用 `ImageGenerationProvider`，不得用具体图片模型定义项目级能力。
- 生图工具仅在设置页统一新增、编辑和删除；参考图生成（含批量）和漫画出图只选择已有工具。
- 每个工具必须选择自己消费的 `ImagePromptType`，生成时只读取页面下相同类型且未过期的最新 ImageSpec。
- ComfyUI 工具通过受限 binding 把 `prompt.positive`、`prompt.negative`、`render.seed` 和可选参考条件注入 workflow；不要猜测节点，也不要暴露任意表达式求值。
- 工具声明 `capabilities.reference_images` 的容量、编号格式、传输方式和画布需求。ComfyUI 用有序 `reference_slots`，每槽独立 loader，并显式列出空槽需断开的消费输入。外 API 只使用配置的 multipart 原图数组或 JSON data URL 数组及编辑接口，不按模型名称分支。
- `reference_inputs` 是实际传输清单，由选图计划按工具容量/本地文件/绑定检查冻结。容量先保各对象主图再辅助，省略项记录提示；Prompt 编号与清单顺序一致，不能上传所有递归身份资产或把省略图片仍描述为已传入。独立参考图任务显式选择的输入仍须完整传入。
- 新批次 `input_snapshot_json` 冻结页 ID、ImageSpec、实际参考顺序、编号 Prompt、工具参数与 seed；暂停继续读取冻结输入，不读取新素材重新选择或受当前工具参数变化影响。继续时仍校验原文件可读且 SHA256 未变，API Key 只读取当前本地工具，不进入快照。历史规格和缺少快照的批次按旧入口兼容，但其真实传图顺序必须标为未知，不能推断已经冻结。
- ComfyUI 的底模、LoRA、采样器和调度器保留在 workflow JSON 内，不进入 ImageSpec、项目配置或运行 manifest。
- OpenAI Images 兼容 Provider 可以在工具配置内部保存具体 `model`，但该值不得反向影响 ImageSpec 编译或项目数据模型。
- 批量图片生成按“每页一次 ComfyUI `/prompt` 请求”提交，不一次性提交全部页面。
- 生成结果追加保存到 `comic_image`，不要自动删除旧候选图，方便人工比较。
- 出图工作台默认仅生成没有任何候选图的页面，也可勾选页面追加重画；没有最终选图不等于缺图。新任务接受明确页 ID 范围，冻结快照仅包含本次范围；续跑继续沿用原冻结输入，不能自动重新准备。
- `GenerationMode` 及 API 参数仅保留历史兼容；新准备和新出图使用统一流程，旧请求中的模式选择不生效。旧冻结批次续跑仍读取原批次参数、工具和输入，不把旧未冻结规格伪装成冻结批次。
- 图片生成暂停只停止提交后续页面，不调用 ComfyUI interrupt，不中断已经提交的当前 prompt。
- ComfyUI 调用只允许出现在 Tool/Service 层，Agent 不直接调用 ComfyUI。

## 旁路一致性评测

- 保留 ViStoryBench 指标、参考值配置、不可变评测快照和历史结果，仅由用户按需启动，不作为出图、人工选图或完成漫画的硬性门槛。
- 已完成批次可用于评测，不要求历史 `final` 模式；评测自身仍检查完整候选套组、身份基准和运行环境。环境或评测失败不影响逐页选图。
- 参考值只标记是否达到比较基准；人工可采用已完成评测的任意完整套组，低分不阻止采用。整套采用仍校验其输入未过期；逐页选图不查询评测。
- 旧 `/gate` 接口兼容返回是否每页已人工选图，`evaluation_required` 为 `false`，不读取评测分数。

## 开发与验证

### 本地测试产物目录

- 仓库根目录的 `.codex-artifacts/` 是自动化代理和本地验收统一使用的临时产物目录，只供本机使用，不得提交。
- 浏览器 Profile、E2E 图片、测试数据库、pytest `--basetemp`、smoke 输出和临时日志必须写入 `.codex-artifacts/`，不要散落在仓库根目录或源码目录。
- 可复用的测试代码和 fixture 必须放入正式测试目录；不要把需要版本控制的测试资源放进 `.codex-artifacts/`。

后端安装依赖：

```bash
conda activate comaic
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
from backend.services.project_service import ProjectService
from backend.services.outline_service import OutlineService

init_db()
with SessionLocal() as session:
    repo = ComicRepository(session)
    project = ProjectService(repo).create_project(title="Demo")
    outline_session = OutlineService(repo).create_outline_session(project_id=project.id)
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
- 设置页会按本地 MVP 需求回显明文 API Key；不要在日志、README、测试快照或回复中额外复述 key。
- `data/` 中的真实数据库、`outputs/` 中的生成图片不要提交，除非明确是小型 fixture。
- 网络调用可能产生费用，默认测试应避免实际调用 DeepSeek。

## 给后续代理的工作建议

1. 先运行 `git status --short`，确认当前工作区是否已有用户改动。
2. 修改前读取相关文件，不要根据文件名猜实现。
3. 保持改动聚焦，避免顺手重构无关模块。
4. 新增后端依赖要同步更新 `backend/requirements.txt`；新增前端依赖要同步更新 `frontend/package.json`。
5. 新增 prompt 要放在 `backend/prompts/`，不要硬编码在 Python 里。
6. 完成后至少做一次导入级验证；若无法运行，说明原因。
