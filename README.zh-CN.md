# Comaic

[English](./README.md) | 简体中文

comaic 是一个本地优先的 AI 漫画生成工作台。它把“故事大纲 -> 分页脚本 -> 文生图 Prompt -> ComfyUI 图片生成 -> 人工选图”串成一条可操作的 MVP 链路，适合用来实验 AI 辅助漫画创作流程。

当前版本重点不是自动完成所有创作判断，而是让每个关键产物都能被用户确认和调整：大纲可以多轮对话生成，分页脚本可以人工编辑，图片 Prompt 可以重新生成，ComfyUI 候选图可以逐页选择最终版本。

## 功能概览

- 项目管理：创建、编辑、删除漫画项目。
- 大纲工作台：与 Outline Agent 多轮对话，实时流式显示回复，并保存大纲版本。
- 分页脚本：基于大纲版本生成分页漫画脚本，支持批量生成、暂停、删除分段和人工编辑。
- 图片 Prompt：维护“脚本转文生图 Prompt”的 System Prompt，并为已完成脚本任务批量生成图片 Prompt。
- 图片生成：维护 ComfyUI Workflow preset，基于页面图片 Prompt 调用本地 ComfyUI 生成候选图。
- 人工选择：为每页候选图选择最终图片。
- 多语言前端：当前支持中文和英文。

## 技术栈

- Backend：Python、FastAPI、LangChain、DeepAgents、SQLAlchemy、SQLite、SSE
- LLM：DeepSeek OpenAI-compatible API
- Frontend：Vue 3、Vite、Element Plus、vue-i18n
- Image Generation：本地 ComfyUI HTTP API

## 项目结构

```text
comaic/
├── backend/      # FastAPI + LangChain + SQLAlchemy
├── frontend/     # Vue 3 + Vite + Element Plus
├── data/         # SQLite，本地开发数据
├── outputs/      # ComfyUI 生成图片保存目录
├── workflows/    # 可选：本地 workflow_api.json 备份
├── start.sh      # 同时启动前后端的本地脚本
├── README.md
├── README.zh-CN.md
├── AGENTS.md
└── .gitignore
```

## 环境要求

- Python 3.12
- Node.js 20.19+ 或 22.12+
- npm
- Conda，推荐环境名：`lang_graph`
- 本地 ComfyUI，默认地址：`http://127.0.0.1:8188`
- DeepSeek API Key

## 快速开始

### 1. 克隆项目

```bash
git clone <your-repo-url> comaic
cd comaic
```

### 2. 创建并激活 Python 环境

```bash
conda create -n lang_graph python=3.12
conda activate lang_graph
```

### 3. 安装后端依赖

```bash
pip install -r backend/requirements.txt
```

### 4. 安装前端依赖

```bash
cd frontend
npm install
cd ..
```

### 5. 配置环境变量

从示例文件创建本地 `.env`：

```bash
cp backend/.env.example .env
```

编辑 `.env`：

```env
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

DATABASE_URL=sqlite:///data/comaic.sqlite3
COMFYUI_BASE_URL=http://127.0.0.1:8188
```

真实 `.env` 不要提交到 Git。首次启动时，系统会用 `.env` 初始化默认模型配置；启动后也可以在右上角“设置”页面维护多组 OpenAI 兼容 API、API Key，以及每组 API 下的多个模型名。页面保存后，新建的 Agent 调用会优先使用 SQLite 中 active 配置的默认模型。

### 6. 启动 ComfyUI

请先按 ComfyUI 官方方式启动本地服务，并确保浏览器可访问：

```text
http://127.0.0.1:8188
```

### 7. 启动 comaic

推荐使用根目录脚本同时启动前后端：

```bash
./start.sh
```

默认地址：

- 前端：http://127.0.0.1:5173
- 后端：http://127.0.0.1:8000
- 后端健康检查：http://127.0.0.1:8000/health

也可以分开启动：

```bash
uvicorn backend.main:app --reload
```

```bash
cd frontend
npm run dev
```

## 使用流程

### 1. 创建项目

进入“项目”页面，点击“新建项目”，输入项目标题。

项目只是创作容器；大纲、脚本、图片 Prompt 和图片生成任务都会关联到具体项目。

### 1.1 配置模型

点击右上角“设置”按钮，进入模型配置页：

1. 填写配置名称和 OpenAI 兼容 API Base URL。
2. 填写一个或多个模型名。
3. 填写 API Key。
4. 可选点击“测试连接”，确认配置可用。
5. 选择默认模型，并点击“保存设置”。
6. 如有多组 API 配置，点击“设为当前使用”切换 active 配置。

出于安全考虑，后端不会把已保存的 API Key 回显给前端。API Key 保存在本地 SQLite 数据库中，请不要提交 `data/` 目录。

### 2. 生成大纲

进入“大纲工作台”：

1. 选择项目。
2. 创建或进入大纲会话。
3. 与 Agent 多轮对话，补充题材、主角、背景、冲突、结尾方向等信息。
4. 每轮对话结束后，如果 Agent 判断大纲需要更新，右侧会保存新的大纲版本。

大纲版本是后续分页脚本生成的输入。

### 3. 生成分页脚本

进入“分页脚本”页面：

1. 选择项目。
2. 选择该项目下的大纲版本。
3. 输入目标总页数和补充要求。
4. 点击批量生成。

系统会先生成故事节奏分段，再按分段生成页面脚本。页面脚本当前采用结构化字段：

- 摘要
- 人物
- 服装
- 场景
- 构图
- 人物动作
- 对话

生成完成后，你可以查看、编辑、清空或删除页面脚本。批量生成过程中可以暂停，暂停后已生成内容会保留。

### 4. 生成图片 Prompt

进入“图片 Prompt”页面：

1. 维护“脚本 -> 文生图 Prompt”的 System Prompt preset。
2. 选择项目。
3. 选择已完成的脚本生成任务。
4. 选择 System Prompt preset。
5. 点击生成。

系统会将每页结构化脚本转成适合文生图模型使用的正向 Prompt，并保存到页面数据中。再次生成同一任务的图片 Prompt 时，会先清空该任务已有 Prompt，再实时写入新的结果。

### 5. 配置 ComfyUI Workflow

进入“图片生成”页面，先维护 Workflow preset。

Workflow preset 需要使用 ComfyUI 的 API workflow JSON，而不是普通界面 workflow。你可以：

- 直接粘贴 workflow API JSON。
- 拖拽或选择 `.json` 文件。
- 使用“自动解析正向节点”自动识别正向 Prompt 节点 ID 和输入名。

至少需要配置：

- Workflow JSON
- 正向 Prompt 节点 ID
- 正向 Prompt 输入名，常见为 `text`

Seed 节点可选；如果不配置，系统不会强行注入 seed，而是使用 workflow 自身配置。

### 6. 生成图片

在“图片生成”页面：

1. 选择项目。
2. 选择已完成脚本任务。
3. 选择 Workflow preset。
4. 设置每页候选图数量和轮询间隔。
5. 点击生成。

当前批量图片生成策略是：每一页单独提交一次 ComfyUI `/prompt` 请求。后端会轮询 `/history/{prompt_id}`，通过 `/view` 下载生成图片，并保存到 `outputs/`。

再次生成不会删除旧图，而是追加新的候选图，方便人工比较。生成过程中可以点击暂停；暂停只会停止提交后续页面，不会中断已经提交给 ComfyUI 的当前任务。

### 7. 选择最终图片

每页生成候选图后，可以在“图片生成”页面查看缩略图，并为该页选择一张最终图片。

## ComfyUI Workflow 说明

comaic 不内置固定 ComfyUI 工作流。你需要在页面中维护自己的 Workflow preset。

推荐做法：

1. 在 ComfyUI 中搭好文生图 workflow。
2. 导出 API workflow JSON。
3. 在 comaic 的“图片生成”页面新增 Workflow preset。
4. 拖入 JSON 文件或粘贴 JSON。
5. 确认正向 Prompt 节点 ID 和输入名。
6. 保存 preset 后用于图片生成。

如果 workflow 里有多个 `CLIPTextEncode` 节点，前端会尝试避开明显的 negative prompt 节点，但仍建议你手动检查一次。

## 常用命令

后端导入和建表检查：

```bash
python -c "from backend.models.database import init_db; init_db(); print('db ready')"
```

前端类型检查：

```bash
cd frontend
npm run type-check
```

前端构建：

```bash
cd frontend
npm run build
```

后端文案 catalog 更新：

```bash
pybabel extract -F backend/babel.cfg -o backend/locales/messages.pot backend
pybabel update -i backend/locales/messages.pot -d backend/locales
pybabel compile -d backend/locales
```

前端界面和进度时间线文案由 `vue-i18n` 管理；后端业务错误会返回稳定 `code` 和按请求语言本地化后的 `message`。前端请求会自动携带当前界面语言。

## 本地数据

- SQLite 默认保存到 `data/comaic.sqlite3`
- 生成图片默认保存到 `outputs/`
- `.env`、`data/`、`outputs/`、`frontend/node_modules/`、`frontend/dist/` 不应提交到 Git

当前项目仍是 MVP，本地 SQLite 没有引入正式迁移工具。如果开发期间 ORM 表结构变化导致旧库不兼容，可以删除本地数据库后重启：

```bash
rm data/comaic.sqlite3
./start.sh
```

时间字段以带 `+00:00` 的 UTC ISO8601 字符串写入 SQLite，页面展示时会自动转成浏览器本地时间。若你从旧版本升级到当前版本，请删除旧的本地 SQLite 后重建。

如果你已经积累了重要数据，请先备份数据库。

## 常见问题

### 前端 5173 和后端 8000 是什么关系？

前端 Vite 默认运行在 `5173`，后端 FastAPI 默认运行在 `8000`。前端通过 Vite proxy 将 `/api` 请求转发到后端。

### 为什么需要先启动 ComfyUI？

图片生成阶段会调用本地 ComfyUI HTTP API。如果 ComfyUI 没有启动，图片生成请求会失败。

### Workflow JSON 拖入后没有识别到正向 Prompt 节点怎么办？

请确认拖入的是 ComfyUI API workflow JSON，并手动填写正向 Prompt 节点 ID 和输入名。常见输入名是 `text`。

### 图片生成会覆盖旧候选图吗？

不会。图片生成采用追加候选图的方式，旧图会保留，便于比较和选择。

### 暂停图片生成会中断 ComfyUI 当前任务吗？

不会。暂停只阻止后续页面继续提交给 ComfyUI，当前已经提交的页面会继续跑完并保存结果。

### DeepSeek 报 API Key 错误怎么办？

检查根目录 `.env` 中是否配置了：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
```

不要把真实 key 写入代码或提交到 Git。

## 开发状态

comaic 目前是 MVP 版本，核心链路已经跑通，但仍适合继续扩展：

- 更稳定的任务恢复与进度重连
- 更完整的数据库迁移
- 更丰富的 ComfyUI workflow 参数注入
- 图片生成恢复继续
- 更细的权限、项目导出和部署方案

欢迎基于这个项目继续实验和改造 AI 漫画创作流程。
