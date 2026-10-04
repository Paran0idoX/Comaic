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

一致性评测是可选旁路，直接复用 `comaic` 环境；出图和人工选图不依赖评测运行时。需要评测时，安装与本项目验证版本一致的 CUDA 版 PyTorch、指标依赖，并显式下载固定版本权重：

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

生图准备直接读取每页绑定的角色基准、当前造型和场景。同一角色的固定外貌、同一造型的描述跨页复用，动作、表情及局部变化来自本页脚本。湿衣、破损等需要持续出现的剧情细节，应在每个相关页面明确写出。新准备不再提取跨页事件或重放连续性状态机；历史事件与状态快照保留审计。

生成完成后，你可以查看、编辑、清空或删除页面脚本。批量生成过程中可以暂停，暂停后已生成内容会保留。

列表直接显示关联人物和关联场景，详情展示人物基准、当前分段造型、场景条目和本页时段、天气、光照、氛围。编辑时可多选当前分段人物、单选当前批次场景，并填写环境条件；无人物页面可留空人物选择。关联、条件和脚本文字一起保存，不自动改写文字，保存后通过现有复审入口重新审查。人工新增页面必须选择场景。

新场景条目只描述固定地点，例如“教学楼储物间”的建筑、布局、材质和固定陈设。白天晴天和夜晚雨天页面绑定同一地点、共用参考图，各自条件保存在页面中并进入三种生图提示词。规划通过明确目录 key 复用固定地点；旧日夜场景不会自动合并。历史页未保存独立条件时展示原场景条件，保存后只覆盖本页。修改关联或条件只让受影响页准备过期并取消旧最终选择，候选图保留，冻结出图批次沿用原快照。

### 4. 维护已确认的画面设定并编译 ImageSpec

先进入“画面设定”审核分页脚本自动生成的服装与场景草稿，再为人物、场景和物品准备参考图。每张图片保存为独立原图，不拼成参考板。人物细分为脸部、全身正面、侧面和背面，半身仅保留历史读取；场景和物品各自有名称及描述，脚本场景可以绑定到场景条目。分类内置于代码，后续可扩展。

“确认可用”采用单选规则：同一对象、用途及适用范围只保留一张已确认参考图。确认新图后，旧图退回待确认候选，可随时重新选回；生成原图再次确认时复用已有素材。人物各用途分别选择，身体图还区分服装版本；新场景直接按条目选择，上传、单次及批量生成和快速选图无需“适用场景”。新场景参考图只展示固定建筑、布局、材质和陈设，不消费剧情时段、天气、光照或临时物件状态。旧场景仍可分别选择通用图与版本专用图；物品按对象选择。

按参考类别生成或上传图片，预览后点击“确认可用”。人物图片带有明确的人物归属和用途，身体参考还可以关联服装版本；无需凑齐四种视角，也不强制独立服装图片。“完整详情”展示完整设定。从当前分段角色或场景进入编辑后，可直接“保存并应用”，一次创建已确认版本并绑定到界面注明的目标，也可“仅存草稿”。从素材库复制仍默认保存草稿；其它分段及历史版本保持不变。历史画风配置保留审计，新生图准备不再应用或要求选择画风。

参考图生成描述使用“原始设定 → 缓存视觉摘要 → 按用途编译 → 人工检查 → 冻结生成”。首次准备使用当前语言模型；切换视角、工具和尺寸复用摘要。展开“视觉摘要”可修改英文事实及互斥外观的选定值，原始设定不变。来源或格式变化时摘要失效，修订冲突时须重新准备。单张与批量任务的创建、运行和继续只使用冻结摘要及手改描述，不再调用语言模型。提炼失败保留编辑并禁止提交，新流程不增加画风来源。

参考图是可选增强，不再提供普通/严格模式选择。缺少人物、场景或可见物品参考时提示，仍可使用固定文字设定生成。实际传入的文件必须可读且内容未变；无效文件或工具配置在任何上传和提交前拦截。

脚本完成后进入“生图准备”，选择最终提示词语言并准备每页的三种提示词，再到“漫画出图”选择工具生成图片。出图只读取已有提示词，不自动准备或转换语言。缺少或过期时须返回生图准备：

1. 选择项目与已完成的脚本任务。
2. 按需维护 ShotPlanner 和 Negative Prompt preset。
   “最终提示词语言”可选保持原文、中文或英文，仅在生图准备中设置。选择中文或英文时，当前模型会忠实转换最终正向、负向的四个组件，每页仅转换一次，三种格式共用译文；原始脚本和设定不变。切换语言后点击准备以生成新提示词，已冻结批次继续使用原 Prompt。
3. 显式准备每页提示词，查看缺少参考图等提示。
4. 按页查看 tag、自然语言和 hybrid 三个标签页。

三种 ImageSpec 共用同一份 ShotPlan 和有序参考图计划。ShotPlanner 判断本页可见范围、朝向、背景和目录物品，再由确定规则选择已确认原图，不额外调用视觉 AI 看图。脸部使用 `脸部／全身`；半身、全身和未知景别使用 `全身／脸部`；侧面使用 `侧面／全身／脸部`；背面使用 `背面／全身／侧面／脸部`。半身仍是镜头范围，不再对应新建的独立参考图用途。同类优先最新确认版本。明确属于其它服装版本的身体图不选；没有服装归属的图片仅用于身份与视角，仍以本页已确认服装为准。背面镜头不额外加入脸部辅助图。

计划先按镜头前后顺序和人物 key 排列所有人物主图，再排列人物辅助图、可见场景、可见目录物品。新场景读取绑定条目的通用图，只参考固定空间，实际环境以本页条件为准；历史场景仍优先读取当前版本专用图，其它版本或其它条目的专用图不会串入本页。每张图都有归属、用途及选用或省略说明。Hybrid 保留两种 Prompt 组件，并按“自然语言 + 换行 + tag”组合最终正向和负向 Prompt。只有三种规格都成功后，页面才会进入 `spec_ready`。参考图确认、撤回、替换或归属变更会让已有准备过期，需要重新编译。

### 5. 配置生图工具

进入“设置 → 生图工具”统一新增、编辑或删除工具 preset。参考图生成（含批量）和漫画出图只选择已有工具。每个工具必须选择 Provider 和它消费的 Prompt 类型：

- `comfyui`：粘贴 ComfyUI API workflow JSON，并用受限 binding 显式绑定正向 Prompt、负向 Prompt、Seed 和可选参考条件。底模、LoRA、采样器、调度器都留在 workflow 内。
- `openai_images_compatible`：配置兼容 API 地址、路径、API Key、模型与返回格式。具体模型只属于该工具，不影响项目和 ImageSpec。

Comaic 不猜测 workflow 中的模型和采样配置。ComfyUI 工具至少需要绑定 `prompt.positive`；提交前检查节点、binding 和实际传图配置。工具不支持可选 Seed 或负向条件时记录提示。

工具需要声明最多参考图数量、Prompt 编号格式（`image N`、`Picture N` 或 `[N]`），以及是否要求显式编辑画布。ComfyUI 使用有序 `reference_slots`，每槽有独立图片加载节点，并显式列出空槽需要断开的消费节点输入；外部图片 API 可配置 multipart 原文件数组或 JSON data URL 数组、编辑接口路径和图片字段。图片独立传输，顺序与最终 Prompt 编号一致。容量不足时优先保留各可见对象的主图，再保留辅助图，并说明省略项。独立参考图任务显式选择的输入仍须完整传入。旧工具配置仍可读取，使用参考图时需补齐传输方式或槽位配置。

### 6. 生成图片

在“漫画出图”页面：

1. 选择项目。
2. 选择已完成脚本任务。
3. 选择生图工具和每页候选图数量。
4. 默认补齐还没有任何候选图的页面；需要重画时勾选页面，界面会显示本次页数和候选数。
5. 确认已完成生图准备后点击生成；轮询、Seed 等参数保留在高级设置。

生成前，后端从实时脚本、角色、造型、场景和参考素材计算逐页来源 Hash；提示词缺少或过期时，在任何上传和提交前拒绝，需返回生图准备显式重新准备。改一页不会让其它页过期，修改角色或场景只影响引用该设定的页面。三类提示词共享一份 ShotPlan，出图使用工具所需的类型与已准备的语言，不调用语言模型。Seed 按所选的逐页或跨页共用候选策略分配；共用策略在所有页面复用同一候选序号的 seed。结果统一保存到 `outputs/`。

所有页面在第一次上传或生成请求前先完成本地检查。批次会冻结页 ID、ImageSpec、实际传图顺序、编号 Prompt、工具参数和 seed；继续同一批次时沿用保存的输入，不随素材库、工具设置或 Prompt 编译器变化重新选图或重写描述，但仍检查冻结原图是否可读且内容未变。API Key 读取当前本地配置，不写入该快照。旧连续性流程产生但尚未开始生图的规格需要重新准备。缺少冻结输入快照的历史批次无法还原已知的参考图输入顺序。

有候选图但尚未选定最终图的页面不算缺图。勾选重画不会删除旧图或已有选图，而是追加候选，方便人工比较。生成过程中可以点击暂停；暂停只会停止提交后续页面，不会中断已经提交给 ComfyUI 的当前任务。

### 7. 选择最终图片

每页生成候选图后，可以在“漫画出图”页面查看缩略图，并为该页选择一张最终图片。

### 8. 按需运行旁路一致性评测

一致性评分仅辅助比较，不限制出图或人工选图。需要评测时，在“画面设定”为大纲角色标记 `写实人物`、`风格化人物` 或 `非人角色`，并准备已确认、本地可读的身份参考图。脸部、全身和侧面图可进入不可变身份基准；实际人脸编码仍需检测到脸，背面图不进入人脸评测。在“漫画出图”选择已完成、包含完整候选套组的批次后手动启动评测。同批次、同候选序号跨全部脚本页面形成一条轨道，不拼接历史批次或自动选图。缺少评测输入或运行环境仅影响评测。

ViStoryBench 保留六项指标和比较参考值；所有适用指标达到参考值时，套组标记为“达到参考值”，结果不作为选图门槛。参考值可在“设置”维护，每次任务保存不可变快照：

- `CIDS cross`：角色相对身份参考图的一致性，越高越好。
- `CIDS self`：同一角色跨页面的一致性，越高越好；没有重复出场角色时为 N/A。
- `CSD cross`：每页生成图相对该页出场角色可用于评估基准的已确认身份参考图的画风一致性，越高越好。
- `CSD self`：整部漫画跨页面风格一致性，越高越好；单页故事为 N/A。
- `OCCM`：预期人物数量与检测人物数量的匹配度（0–100），越高越好。
- `Copy-paste`：人物与参考图的复用倾向，越低越好；该指标不能定位跨页复制区域。

可以不评测直接逐页选图，也可人工采用已完成评测的整套候选，低分不阻止采用。整套采用仍校验评测输入未改变；历史完成检查接口只判断每页是否已选最终图，不要求评测。若 ComfyUI 正在工作，评测会等待队列空闲，再请求卸载模型/释放显存，不会 interrupt 当前生成任务；等待上限由 `CONSISTENCY_COMFYUI_WAIT_TIMEOUT` 控制。

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

设置页新增“系统提示词”树：API 组 → 模型 → 全局 SystemPrompt，以及大纲生成、脚本生成和 Shot 生成的任务提示词。各层可展开/折叠，叶节点支持编辑、保存、查看默认模板和恢复默认。模型全局提示词与任务提示词通过统一请求入口组合一次，不进入会话记忆；保存空全局文本可关闭注入。覆盖保存在本地 SQLite，Markdown 默认文件不改写，后续新建的 Agent/模型调用才读取新设置。现有 Shot preset 保留兼容，设置中的 Shot 覆盖优先；恢复默认也将旧默认 preset 恢复为 Markdown 内容。
