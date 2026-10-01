# Comaic

[English](./README.md) | 简体中文

Comaic 是一个本地优先的 AI 漫画生成工作台。它把“故事大纲 -> 分页脚本 -> 已确认的画面设定 -> 三类 ImageSpec -> 生图 Provider -> 人工选图”串成一条可操作的 MVP 链路，适合用来实验 AI 辅助漫画创作流程。

当前版本重点不是自动完成所有创作判断，而是让每个关键产物都能被用户确认和调整。项目数据不绑定具体图片模型：系统为每页同时编译 tag、自然语言和混合型 Prompt，真正的底模、LoRA 与采样参数留在生图工具内部。

## 功能概览

- 项目管理：创建、编辑、删除漫画项目。
- 故事大纲：与 Outline Agent 多轮对话，实时流式显示回复，并保存大纲版本。
- 分页脚本：基于大纲版本生成分页漫画脚本，支持批量生成、暂停、删除分段和人工编辑。
- 画面设定：确认人物、服装和场景，按分类生成或上传独立参考原图。
- 生图准备：维护 ShotPlanner/Negative Prompt preset，并为每页同时编译 tag、自然语言、混合型 ImageSpec。
- 图片生成：按 Prompt 类型配置 ComfyUI 或 OpenAI Images 兼容工具，并生成页面候选图。
- 人工选择：为每页候选图选择最终图片。
- 多语言前端：当前支持中文和英文。

## 技术栈

- Backend：Python、FastAPI、LangChain、SQLAlchemy、Alembic、SQLite、SSE
- LLM：设置页支持的 LangChain Provider
- Frontend：Vue 3、Vite、Element Plus、vue-i18n
- Image Generation：本地 ComfyUI 或 OpenAI Images 兼容 API

## 项目结构

```text
Comaic/
├── backend/      # FastAPI + LangChain + SQLAlchemy
├── frontend/     # Vue 3 + Vite + Element Plus
├── data/         # SQLite，本地开发数据
├── outputs/      # ComfyUI 生成图片保存目录
├── workflows/    # 可选：本地 workflow_api.json 备份
├── start.ps1     # 推荐的 Windows PowerShell 启动入口
├── start.py      # 同终端启动前后端，支持后端重载和 Vite HMR
├── start.sh      # 保留给 Bash 开发环境的启动脚本
├── README.md
├── README.zh-CN.md
├── AGENTS.md
└── .gitignore
```

## 环境要求

- Python 3.12
- Node.js 20.19+ 或 22.12+
- npm
- Conda，推荐环境名：`comaic`
- 可选本地 ComfyUI，默认地址：`http://127.0.0.1:8188`
- 在设置页配置的模型 Provider API Key

## 快速开始

### 1. 克隆项目

```bash
git clone --recurse-submodules <your-repo-url> Comaic
cd Comaic
```

已有工作副本需要补齐固定版本的 ViStoryBench 子模块时，执行：

```bash
git submodule update --init --recursive
```

### 2. 创建并激活 Python 环境

```bash
conda create -n comaic python=3.12
conda activate comaic
```

### 3. 安装后端依赖

```bash
pip install -r backend/requirements.txt
```

### 4. 安装 ViStoryBench 一致性评估运行时

一致性准出基线直接复用 `comaic` 环境。先安装与本项目验证版本一致的 CUDA 版 PyTorch，再安装指标依赖并显式下载固定版本权重：

```bash
pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cu130
pip install -r backend/requirements-vistorybench.txt
python -m backend.evaluation.setup_runtime --download
```

最后一条命令会校验 ViStoryBench 源码提交和核心权重的 SHA-256，并输出 `ready: true`。权重默认保存到已忽略的 `data/models/vistorybench/`；正常评估只读本地文件，绝不会隐式联网下载。没有 CUDA 12/cuDNN 9 ONNX 动态库时，ArcFace 会明确回退到 CPU，其余 PyTorch 指标仍使用 CUDA；可在设置页查看实际 Provider。

仅检查现有安装、不下载任何文件：

```bash
python -m backend.evaluation.setup_runtime
```

### 5. 安装前端依赖

```bash
cd frontend
npm install
cd ..
```

### 6. 配置环境变量

从示例文件创建本地 `.env`：

```bash
cp backend/.env.example .env
```

编辑 `.env`：

```env
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

DATABASE_URL=sqlite:///data/comaic.sqlite3
COMFYUI_BASE_URL=http://127.0.0.1:8188

VISTORYBENCH_ROOT=third_party/vistorybench
VISTORYBENCH_PRETRAIN_PATH=data/models/vistorybench
CONSISTENCY_COMFYUI_WAIT_TIMEOUT=1800
```

真实 `.env` 不要提交到 Git。首次启动时，系统只用 `.env` 初始化默认模型名和配置壳；API Key 不从环境变量读取，必须在右上角“设置”页面保存。页面保存后，新建的 Agent 调用会优先使用 SQLite 中 active 配置的默认模型。

### 7. 可选：启动 ComfyUI

使用 `comfyui` Provider 时，请先按 ComfyUI 官方方式启动本地服务，并确保浏览器可访问：

```text
http://127.0.0.1:8188
```

### 8. 启动 Comaic

启动器会在同一个终端启动前后端；后端源码或 Prompt 变化时由启动器重启，前端继续使用
Vite HMR。Windows 推荐使用 PowerShell 入口：

```powershell
.\start.ps1
```

其它平台或需要直接调用 Python 时：

```bash
python start.py
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

在全局顶部的项目选择框中点击“新建项目”，输入项目标题。所有工作台共用当前项目；脚本和出图批次在对应页面选择。

项目只是创作容器；大纲、脚本、已确认的画面设定、ImageSpec 和图片生成任务都会关联到具体项目，但项目不会绑定某个具体图片模型。

### 1.1 配置模型

点击右上角“设置”按钮，进入模型配置页：

1. 选择 LangChain Provider；如果选择 OpenAI（兼容），再填写 API Base URL。
2. 填写一个或多个模型名。
3. 填写 API Key。
4. 可选点击“测试连接”，确认配置可用。
5. 选择默认模型，并点击“保存设置”。
6. 如有多组 API 配置，点击“设为当前使用”切换 active 配置。

本地 MVP 会在设置页明文回显已保存的 API Key。API Key 保存在本地 SQLite 数据库中，请不要提交 `data/` 目录。

### 2. 生成大纲

进入“故事大纲”：

1. 选择项目。
2. 创建或进入大纲会话。
3. 与 Agent 多轮对话，补充题材、主角、背景、冲突、结尾方向等信息。
4. 每轮对话结束后，如果 Agent 判断大纲需要更新，右侧会保存新的大纲版本。
5. 检查右侧“角色基准设定”，确认角色名称、身份、背景、固定样貌和默认造型。
6. 点击“确认大纲”，同时确认当前大纲版本和角色基准设定。

只有已确认的大纲版本才能用于后续分页脚本生成。大纲阶段的角色基准设定保存不常改变的角色识别信息；发型、服装、配件、色彩只是默认值，脚本阶段可以按分段覆盖。

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

脚本生成阶段会按分段细化角色设定，例如当前分段中的服装、发型、情绪、身体状态和临时变化。保存这些设定时，系统会同步创建并绑定画面设定中的服装草稿和场景设定草稿；相同内容会复用，继续生成不会覆盖人工选择。ImageSpec 编译时会同时使用大纲角色基准、分段角色设定、画面设定和单页脚本。

生成完成后，你可以查看、编辑、清空或删除页面脚本。批量生成过程中可以暂停，暂停后已生成内容会保留。

### 4. 维护已确认的画面设定并编译 ImageSpec

先进入“画面设定”审核分页脚本自动生成的服装与场景草稿，再为人物、场景和物品准备参考图。每张图片保存为独立原图，不拼成参考板。人物细分为脸部、半身、全身、侧面和背面；场景和物品各自有名称及描述，脚本场景可以绑定到场景条目。分类内置于代码，后续可扩展。

按参考类别生成或上传图片，预览后点击“确认可用”。人物图片带有明确的人物归属和用途，身体参考还可以关联服装版本；无需凑齐五种视角，也不强制独立服装图片。“完整详情”展示完整设定；“复制并修改”保存新草稿，确认后再点击“使用此版本”选用于指定分段，已有选择不会自动替换。历史画风配置保留审计，新生图准备不再应用或要求选择画风。

参考条件检查分为“宽松”和“严格”（内部枚举仍为 `preview` / `final`）：严格要求本页每个人物有可用身份参考，背景入镜时有场景参考，可见目录物品有物品参考，并检查工具是否能够实际应用所选输入。宽松会说明缺少或省略的条件，再继续生成。

然后进入“生图准备”页面：

1. 选择项目与已完成的脚本任务。
2. 按需维护 ShotPlanner 和 Negative Prompt preset。
3. 选择参考条件检查模式，开始编译。
4. 按页查看 tag、自然语言和 hybrid 三个标签页。

三种 ImageSpec 共用同一份 ShotPlan 和有序参考图计划。ShotPlanner 判断本页可见范围、朝向、背景和目录物品，再由确定规则选择已确认原图，不额外调用视觉 AI 看图。脸部、半身、全身、侧面、背面依次使用以下回退顺序：`脸部／半身／全身`、`半身／全身／脸部`、`全身／半身／脸部`、`侧面／全身／半身／脸部`、`背面／全身／半身／侧面／脸部`；未知景别按全身处理。同类优先最新确认版本。明确属于其它服装版本的身体图不选；没有服装归属的图片仅用于身份与视角，仍以本页已确认服装为准。背面镜头不额外加入脸部辅助图。

计划先按镜头前后顺序和人物 key 排列所有人物主图，再排列人物辅助图、可见场景、可见目录物品。当前选用场景版本的专用图片优先于绑定条目的通用图片；其它版本或其它场景条目的专用图不会串入本页。每张图都有归属、用途及选用或省略说明。Hybrid 保留两种 Prompt 组件，并按“自然语言 + 换行 + tag”组合最终正向和负向 Prompt。只有三种规格都成功后，页面才会进入 `spec_ready`。参考图确认、撤回、替换或归属变更会让已有准备过期，需要重新编译。

### 5. 配置生图工具

进入“漫画出图”页面维护工具 preset。每个工具必须选择 Provider 和它消费的 Prompt 类型：

- `comfyui`：粘贴 ComfyUI API workflow JSON，并用受限 binding 显式绑定正向 Prompt、负向 Prompt、Seed 和可选参考条件。底模、LoRA、采样器、调度器都留在 workflow 内。
- `openai_images_compatible`：配置兼容 API 地址、路径、API Key、模型与返回格式。具体模型只属于该工具，不影响项目和 ImageSpec。

Comaic 不猜测 workflow 中的模型和采样配置。ComfyUI 工具至少需要绑定 `prompt.positive`；Final 模式下，ImageSpec 要求的参考条件与 Seed 也必须被 workflow 能力和 binding 覆盖。

工具需要声明最多参考图数量、Prompt 编号格式（`image N`、`Picture N` 或 `[N]`），以及是否要求显式编辑画布。ComfyUI 使用有序 `reference_slots`，每槽有独立图片加载节点，并显式列出空槽需要断开的消费节点输入；外部图片 API 可配置 multipart 原文件数组或 JSON data URL 数组、编辑接口路径和图片字段。图片独立传输，顺序与最终 Prompt 编号一致。容量不足时优先保留各可见对象的主图，再保留辅助图；严格模式主图放不下则失败。旧工具配置仍可读取，但使用新参考计划前需要补齐容量及传输方式或槽位配置。

### 6. 生成图片

在“漫画出图”页面：

1. 选择项目。
2. 选择已完成脚本任务。
3. 选择与目标 ImageSpec Prompt 类型匹配的生图工具。
4. 设置每页候选图数量和轮询间隔。
5. 点击生成。

生成前，后端会校验当前 ImageSpec 是否过期，并只读取与工具 Prompt 类型相同的最新规格。Seed 按所选的逐页或跨页共用候选策略分配；共用策略在所有页面复用同一候选序号的 seed。结果统一保存到 `outputs/`。

所有页面在第一次上传或生成请求前先完成本地检查。批次会冻结页 ID、ImageSpec、实际传图顺序、编号 Prompt、工具参数和 seed；继续同一批次时沿用保存的输入，不随素材库或工具设置变化重新选图，但仍检查冻结原图是否可读且内容未变。API Key 读取当前本地配置，不写入该快照。缺少这类快照的历史批次无法还原已知的参考图输入顺序。

再次生成不会删除旧图，而是追加新的候选图，方便人工比较。生成过程中可以点击暂停；暂停只会停止提交后续页面，不会中断已经提交给 ComfyUI 的当前任务。

### 7. 选择最终图片

每页生成候选图后，可以在“漫画出图”页面查看缩略图，并为该页选择一张最终图片。

### 8. 运行一致性准出评估

先在“画面设定”为每个大纲角色标记 `写实人物`、`风格化人物` 或 `非人角色`，并为需要身份比对的角色准备已确认、本地可读的参考图。脸部、半身、全身和侧面图可以进入不可变身份评估基准；实际人脸编码仍取决于图片中能否检测到脸。背面图不进入人脸身份评测，也不能满足该评测的参考图就绪条件。然后在“漫画出图”页面选择一个已成功完成的 **严格检查（内部 `final`）** 生成批次并启动评估。评估严格以同一批次、同一候选序号跨全部页面形成一条候选轨道；不会把不同历史批次的图片拼在一起，也不会自动选图或排名。

ViStoryBench 准出采用六项指标的 AND 门槛，阈值可在“设置”中维护，每次任务都会保存不可变阈值快照：

- `CIDS cross`：角色相对身份参考图的一致性，越高越好。
- `CIDS self`：同一角色跨页面的一致性，越高越好；脚本中没有重复出场角色时为 N/A，不阻断准出。
- `CSD cross`：每页生成图相对该页出场角色可用于评估基准的已确认身份参考图的画风一致性，越高越好。
- `CSD self`：整部漫画跨页面风格一致性，越高越好；单页故事为 N/A，不阻断准出。
- `OCCM`：预期人物数量与检测人物数量的匹配度（0–100），越高越好。
- `Copy-paste`：人物与参考图的复用倾向，越低越好；该指标不能定位跨页复制区域。

只有所有适用指标都通过，候选轨道才会标记为通过。人工确认后可一次性采用整条轨道为各页最终图；脚本任务的准出接口只接受仍与该已通过轨道完全一致且源文件未变化的选择。若 ComfyUI 正在工作，评估会等待队列空闲，再请求卸载模型/释放显存，不会 interrupt 当前生成任务；等待上限由 `CONSISTENCY_COMFYUI_WAIT_TIMEOUT` 控制。

## ComfyUI Workflow 说明

Comaic 不内置固定 ComfyUI 工作流，也不在项目层维护 checkpoint、LoRA、采样器或模型许可证。你需要在页面中维护自己的 Workflow preset。

推荐做法：

1. 在 ComfyUI 中搭好文生图 workflow。
2. 导出 API workflow JSON。
3. 在 Comaic 的“漫画出图”页面新增 Workflow preset。
4. 拖入 JSON 文件或粘贴 JSON。
5. 确认 `prompt.positive`、可选 `prompt.negative` 和 `render.seed` 的 binding。
6. 保存 preset 后用于图片生成。

如果 workflow 里有多个 `CLIPTextEncode` 或采样器节点，前端会尝试选择最可能的正向 Prompt 和 Seed 节点，但仍建议你手动检查一次。

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

项目使用 Alembic 管理 SQLite schema，后端启动时会自动升级到当前 revision。开发数据不重要时也可以删除本地数据库后重建：

```bash
rm data/comaic.sqlite3
python start.py
```

时间字段以带 `+00:00` 的 UTC ISO8601 字符串写入 SQLite，页面展示时会自动转成浏览器本地时间。若你从旧版本升级到当前版本，请删除旧的本地 SQLite 后重建。

如果你已经积累了重要数据，请先备份数据库。

## 常见问题

### 前端 5173 和后端 8000 是什么关系？

前端 Vite 默认运行在 `5173`，后端 FastAPI 默认运行在 `8000`。前端通过 Vite proxy 将 `/api` 请求转发到后端。

### 什么情况下需要先启动 ComfyUI？

只有选择 `comfyui` Provider 时才需要。若工具使用 OpenAI Images 兼容 Provider，则不依赖本地 ComfyUI。

### Workflow JSON 拖入后没有识别到正向 Prompt 节点怎么办？

请确认拖入的是 ComfyUI API workflow JSON，并手动填写正向 Prompt 节点 ID 和输入名，或直接编辑 `prompt.positive` binding。常见输入名是 `text`。

### 图片生成会覆盖旧候选图吗？

不会。图片生成采用追加候选图的方式，旧图会保留，便于比较和选择。

### 暂停图片生成会中断 ComfyUI 当前任务吗？

不会。暂停只阻止后续页面继续提交给 ComfyUI，当前已经提交的页面会继续跑完并保存结果。

### DeepSeek 报 API Key 错误怎么办？

打开设置页，确认当前 active 的 DeepSeek 配置已经保存 API Key。

不要把真实 key 写入代码或提交到 Git。

## 开发状态

Comaic 目前是 MVP 版本，核心链路已经跑通，但仍适合继续扩展：

- 更稳定的任务恢复与进度重连
- 更完善的迁移回滚与备份工具
- 更丰富的 ComfyUI workflow 参数注入
- 图片生成恢复继续
- 更细的权限、项目导出和部署方案

欢迎基于这个项目继续实验和改造 AI 漫画创作流程。

### 工作台体验验收（不调用生成服务）

在 `frontend/` 运行 `node --test tests/*.test.cjs`，覆盖流式事件的项目隔离、精确任务定位、离页状态刷新和准备条件。可在项目根目录运行 `python -B frontend/tests/mock_workspace_api.py --port 8000`，配合前端开发服务器检查 1280×720、1440×900 与窄屏布局。该 mock 使用内存测试数据并模拟参考图任务，不调用真实生成服务、不读取真实数据库；退出进程即丢弃上传和修改。主操作放在页面顶部，技术选项默认折叠；后台任务会在打开时刷新并显示更新时间，旧记录缺少定位信息时打开所属项目任务列表。
