<p align="center">
  <img src="./frontend/src/assets/logo/logo-wordmark.svg" alt="Comaic" width="320" />
</p>

English | [简体中文](./README.zh-CN.md)

Comaic is a local-first AI comic generation workspace. It turns the workflow “story outline -> page scripts -> confirmed visual settings -> three ImageSpec prompt forms -> image provider -> manual image selection” into an operable MVP pipeline for experimenting with AI-assisted comic creation.

The current version is not designed to automate every creative decision. Instead, each key artifact remains reviewable and editable. Project data is independent of concrete image models: every page is compiled into tag, natural-language, and hybrid prompts, while checkpoints, LoRAs, and sampling settings remain inside the generation tool.

## Features

- Project management: create, edit, and delete comic projects.
- Outline workspace: run multi-turn conversations with the Outline Agent, stream replies in real time, and save outline versions.
- Page scripts: generate comic page scripts from an outline version, with batch generation, pause, section deletion, and manual editing.
- Visual Settings: confirm characters, outfits and scenes, and generate or upload categorized original reference images.
- Image Preparation: manage ShotPlanner/negative presets and compile tag, natural-language, and hybrid ImageSpecs for every page.
- Image generation: configure ComfyUI or OpenAI Images-compatible tools by prompt type and generate page candidates.
- Manual selection: choose the final image for each page.
- Multilingual frontend: Chinese and English are currently supported.

## Tech Stack

- Backend: Python, FastAPI, LangChain, SQLAlchemy, Alembic, SQLite, SSE
- LLM: LangChain Providers or OpenAI-compatible API
- Frontend: Vue 3, Vite, Element Plus, vue-i18n
- Image generation: local ComfyUI or an OpenAI Images-compatible API

## Project Structure

```text
Comaic/
├── backend/      # FastAPI + LangChain + SQLAlchemy
├── frontend/     # Vue 3 + Vite + Element Plus
├── data/         # Local SQLite development data
├── outputs/      # Saved ComfyUI generated images
├── workflows/    # Optional local workflow_api.json backups
├── start.ps1     # Recommended Windows PowerShell entry point
├── start.py      # Cross-platform launcher with backend reload and Vite HMR
├── start.sh      # Bash launcher kept for shell-based development
├── README.md
├── README.zh-CN.md
├── AGENTS.md
└── .gitignore
```

## Requirements

- Python 3.12
- Node.js 20.19+ or 22.12+
- npm
- Conda, with the recommended environment name `comaic`
- Optional local ComfyUI, default URL: `http://127.0.0.1:8188`
- A model provider API key configured in the Settings page

## Quick Start

### 1. Clone the repository

```bash
git clone --recurse-submodules <your-repo-url> Comaic
cd Comaic
```

For an existing working tree, initialize the pinned ViStoryBench submodule with:

```bash
git submodule update --init --recursive
```

### 2. Create and activate the Python environment

```bash
conda create -n comaic python=3.12
conda activate comaic
```

### 3. Install backend dependencies

```bash
pip install -r backend/requirements.txt
```

### 4. Install the ViStoryBench consistency runtime

The release gate reuses the same `comaic` environment. Install the CUDA build validated by this project, then the metric dependencies, and explicitly materialize the pinned weights:

```bash
pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cu130
pip install -r backend/requirements-vistorybench.txt
python -m backend.evaluation.setup_runtime --download
```

The last command verifies the pinned ViStoryBench source commit and SHA-256 hashes of all core weights, then prints `ready: true`. Weights default to the ignored `data/models/vistorybench/` directory. Evaluation only reads local files and never downloads models implicitly. If the CUDA 12/cuDNN 9 ONNX libraries are unavailable, ArcFace explicitly falls back to CPU while the PyTorch metrics continue to use CUDA; Settings reports the actual provider.

To inspect an existing installation without downloading anything:

```bash
python -m backend.evaluation.setup_runtime
```

### 5. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### 6. Configure environment variables

Create a local `.env` from the example file:

```bash
cp backend/.env.example .env
```

Edit `.env`:

```env
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

DATABASE_URL=sqlite:///data/comaic.sqlite3
COMFYUI_BASE_URL=http://127.0.0.1:8188

VISTORYBENCH_ROOT=third_party/vistorybench
VISTORYBENCH_PRETRAIN_PATH=data/models/vistorybench
CONSISTENCY_COMFYUI_WAIT_TIMEOUT=1800
```

Do not commit your real `.env` file. On first startup, Comaic uses `.env` only to initialize the default model name/config shell. API keys are not read from environment variables; configure them in the top-right “Settings” page. New Agent calls use the active SQLite configuration and its default model.

### 7. Optional: start ComfyUI

When using the `comfyui` provider, start your local ComfyUI server and make sure it is reachable in a browser:

```text
http://127.0.0.1:8188
```

### 8. Start Comaic

The launcher starts both services in one terminal, restarts the backend when backend source or
prompt files change, and keeps Vite frontend HMR. On Windows, use the PowerShell entry point:

```powershell
.\start.ps1
```

On other platforms, or when invoking Python directly:

```bash
python start.py
```

Default URLs:

- Frontend: http://127.0.0.1:5173
- Backend: http://127.0.0.1:8000
- Backend health check: http://127.0.0.1:8000/health

You can also start them separately:

```bash
uvicorn backend.main:app --reload
```

```bash
cd frontend
npm run dev
```

## User Flow

### 1. Create a project

Choose “New Project” in the global project selector at the top. Workspaces share the current project; select script and image batches within their workspace.

A project is the creative container. Outlines, scripts, confirmed visual settings, ImageSpecs, and image generation tasks are associated with it, but the project is not bound to a concrete image model.

### 1.1 Configure the model

Click the top-right “Settings” button:

1. Choose a LangChain Provider, or choose OpenAI Compatible and enter its API Base URL.
2. Enter one or more model names.
3. Enter the API key.
4. Optionally click “Test Connection”.
5. Choose the default model and click “Save Settings”.
6. If you have multiple API configurations, click “Use This Config” to switch the active one.

This local MVP echoes saved API keys in the Settings page. Keys are stored in the local SQLite database, so do not commit the `data/` directory.

### 2. Generate an outline

Open the “Story Outline”:

1. Select a project.
2. Create or reuse an outline session.
3. Chat with the Agent to refine genre, protagonist, setting, conflict, ending direction, and other story information.
4. After each turn, if the Agent decides the outline should be updated, a new outline version is saved on the right.
5. Review the “Character Baseline” area for names, roles, backgrounds, fixed appearance, and default looks.
6. Click “Confirm Outline” to confirm both the outline version and its character baseline.

Only confirmed outline versions can be used for page script generation. The outline-stage character baseline stores stable identity details; hairstyle, clothing, accessories, and colors are defaults that can be overridden later by script sections.

### 3. Generate page scripts

Open the “Page Scripts” page:

1. Select a project.
2. Select an outline version under that project.
3. Enter the target page count and any extra requirements.
4. Start batch generation.

The system first creates story pacing sections, then generates page scripts section by section. Page scripts currently use structured fields:

- Summary
- Characters
- Clothing
- Scene
- Composition
- Character action
- Dialogue

During script generation, each section refines character state for that section, such as current clothing, hairstyle, emotion, physical state, and temporary changes. Saving those settings also creates and binds draft Visual Settings outfits and scene settings; identical content is reused, and resumed generation never replaces a manual selection. ImageSpec compilation combines the outline character baseline, section-level details, the Visual Settings, and the page script.

After generation, you can view, edit, clear, or delete page scripts. Batch generation can be paused, and generated content is kept after pausing.

### 4. Maintain confirmed visual settings and compile ImageSpecs

First use “Visual Settings” to review outfit and scene drafts derived from page scripts, then prepare references for characters, scenes and objects. Each image is stored as an independent original; the application does not build reference collages. Character references have face, half-body, full-body, side and back categories. Scene and object entries have their own name and description, and a script scene can be bound to a scene entry. These categories are defined in code and can be extended later.

Choose a reference category to generate or upload an image, preview it, and confirm that it can be used. Character images carry their character and purpose; body references can also be associated with a clothing version. You do not need all five character views or a separate clothing image. “Full Details” shows the complete setting. “Copy and Edit” saves a new draft; after confirming it, explicitly choose “Use This Version” for a section. Existing selections are preserved. Historical style settings remain available for audit, but new image preparation does not apply them or ask for a style selection.

Reference checks are “Relaxed” and “Strict” (internal enums remain `preview` and `final`). Strict checks require a usable identity reference for each page character, a scene reference when the background is visible, and references for visible catalog objects. They also check that the tool can apply the selected inputs. Relaxed checks explain missing or omitted inputs before generating.

Then open “Image Preparation”:

1. Select a project and a completed script task.
2. Maintain ShotPlanner and Negative Prompt presets when needed.
3. Select the reference-check mode, then compile.
4. Review the tag, natural-language, and hybrid tabs for each page.

All three ImageSpecs share one ShotPlan and one ordered reference plan. The ShotPlanner identifies the visible framing, viewing direction, background and catalog objects; deterministic rules choose the approved images without another visual-AI call. Face, half-body, full-body, side and back requests use these fallback orders respectively: `face / half / full`, `half / full / face`, `full / half / face`, `side / full / half / face`, and `back / full / half / side / face`. Unknown framing uses full-body. Within one category, the latest confirmed version is preferred. Body images explicitly associated with a different clothing version are excluded; images without a clothing association provide identity and viewpoint, while the page's confirmed clothing still governs appearance. Back views do not receive a face-detail auxiliary image.

The plan lists all character primary images first, ordered by ShotPlan depth and character key, followed by character auxiliaries, the visible scene, and visible catalog objects. Selected scene-version images take precedence over the bound scene entry's generic images; references for another version or a different scene entry are excluded. Each image explains its owner, purpose and selection or omission reason. Hybrid keeps both prompt components and combines positive and negative prompts as “natural language + newline + tags.” A page becomes `spec_ready` only after all three forms compile successfully. Reference approval, withdrawal, replacement or ownership changes make existing preparation stale and require a new compilation.

### 5. Configure an image generation tool

Open “Comic Images” and create a tool preset. Every tool selects both a Provider and the prompt type it consumes:

- `comfyui`: paste ComfyUI API workflow JSON and use restricted bindings for positive prompt, negative prompt, seed, and optional reference conditions. The checkpoint, LoRA, sampler, and scheduler stay inside the workflow.
- `openai_images_compatible`: configure the compatible API URL, endpoint, key, model, and response format. The concrete model belongs only to this tool and never changes project or ImageSpec data.

Comaic does not infer model or sampling configuration from a workflow. A ComfyUI tool must at least bind `prompt.positive`; in Final mode, declared capabilities and bindings must also satisfy every condition required by the ImageSpec.

Tools declare their maximum reference-image count, prompt labels (`image N`, `Picture N` or `[N]`), and whether an explicit editing canvas is required. ComfyUI uses ordered `reference_slots`, each with its own image-loader input and explicit consumer inputs to disconnect when that slot is empty. An image API can use multipart original-file arrays or JSON data-URL arrays, with a configured editing endpoint and image field. Images are sent individually in the same numbered order used by the final prompt. Tool limits keep each visible object's primary image before optional auxiliaries; strict checks fail if the primary images do not fit. Legacy presets remain readable, but must declare this capacity and transport or slot configuration before using the new reference plan.

### 6. Generate images

Open the “Comic Images” page:

1. Select a project.
2. Select a completed script task.
3. Select a generation tool whose prompt type matches the target ImageSpec.
4. Set candidate count per page and polling interval.
5. Start generation.

Before generation, the backend rejects stale ImageSpecs and reads only the latest spec matching the tool’s prompt type. Seeds follow the selected per-page or shared-candidate strategy; the shared strategy reuses one seed for the same candidate index across pages. Results from either provider are normalized and stored under `outputs/`.

All pages are checked locally before the first upload or generation request. The batch freezes its page IDs, ImageSpecs, ordered transmitted images, numbered prompt, tool parameters and seeds. Continuing that batch uses the saved inputs even if the reference library or tool settings have changed; it still verifies that the frozen original files are available and unchanged. API keys are read from the current local configuration and are not stored in this snapshot. Historical batches without such a snapshot cannot reconstruct a known reference order.

Regeneration does not delete old images. It appends new candidate images so that you can compare and choose manually. Pausing image generation only stops submitting subsequent pages; it does not interrupt the currently submitted ComfyUI task.

### 7. Select final images

After candidate images are generated, inspect thumbnails in the “Comic Images” page and select one final image for each page.

### 8. Run the consistency release gate

In the Visual Settings, classify every outline character as `realistic human`, `stylized human`, or `non-human`, and add approved, locally readable identity references for characters that require identity comparison. Approved face, half-body, full-body and side images are eligible for the immutable identity-evaluation baseline; actual face encoding still depends on a detectable face. Back images are excluded from face-identity evaluation and cannot satisfy its readiness check. In Image Generation, select a successfully completed **Strict (internally `final`)** generation batch and start evaluation. One track is exactly one candidate index across every page in that batch; images from historical batches are never mixed, ranked, or auto-selected.

The ViStoryBench gate combines six metrics with AND semantics. Thresholds are editable in Settings and every task stores an immutable threshold snapshot:

- `CIDS cross`: character identity consistency against identity references; higher is better.
- `CIDS self`: consistency of the same character across pages; higher is better. It is N/A, and does not block the gate, when the script has no repeated character.
- `CSD cross`: visual-style consistency of each generated page against the eligible approved identity references for its on-stage characters; higher is better.
- `CSD self`: style consistency across the story; higher is better. It is N/A for a one-page story and does not block the gate.
- `OCCM`: matching expected and detected character counts (0–100); higher is better.
- `Copy-paste`: character reuse tendency against references; lower is better. It does not locate copied regions across pages.

A track passes only when every applicable metric passes. After review, you can atomically adopt an entire passing track as the final images. The script release gate accepts the selection only while it still matches that passing track exactly and its source files are unchanged. If ComfyUI is busy, evaluation waits for an idle queue and then asks it to unload models/free VRAM; it never interrupts active generation. `CONSISTENCY_COMFYUI_WAIT_TIMEOUT` controls the maximum wait.

## ComfyUI Workflow Notes

Comaic does not ship with a fixed ComfyUI workflow, and it does not manage checkpoints, LoRAs, samplers, or model licenses at project level. You maintain your own workflow presets in the UI.

Recommended workflow:

1. Build a text-to-image workflow in ComfyUI.
2. Export the API workflow JSON.
3. Add a workflow preset in Comaic’s “Comic Images” page.
4. Drag in the JSON file or paste the JSON content.
5. Confirm bindings for `prompt.positive`, optional `prompt.negative`, and `render.seed`.
6. Save the preset and use it for image generation.

If the workflow contains multiple `CLIPTextEncode` or sampler nodes, the frontend tries to choose the most likely positive prompt and seed nodes, but you should still check the selected nodes manually.

## Common Commands

Backend import and table creation check:

```bash
python -c "from backend.models.database import init_db; init_db(); print('db ready')"
```

Frontend type check:

```bash
cd frontend
npm run type-check
```

Frontend build:

```bash
cd frontend
npm run build
```

Backend message catalog maintenance:

```bash
pybabel extract -F backend/babel.cfg -o backend/locales/messages.pot backend
pybabel update -i backend/locales/messages.pot -d backend/locales
pybabel compile -d backend/locales
```

Frontend UI text and progress timeline text are managed by `vue-i18n`. Backend business errors return a stable `code` plus a localized `message`. Frontend requests automatically include the current UI language.

## Local Data

- SQLite defaults to `data/comaic.sqlite3`
- Generated images default to `outputs/`
- `.env`, `data/`, `outputs/`, `frontend/node_modules/`, and `frontend/dist/` should not be committed to Git

Comaic uses Alembic to manage the SQLite schema and upgrades to the current revision during backend startup. If development data is disposable, you can still delete the database and rebuild it:

```bash
rm data/comaic.sqlite3
python start.py
```

Time fields are stored as UTC ISO8601 strings with `+00:00` and displayed in the browser’s local timezone. If you upgrade from an older version, delete and rebuild the old local SQLite database.

Back up the database first if it contains important data.

## FAQ

### What is the relationship between frontend port 5173 and backend port 8000?

Vite runs the frontend on `5173` by default, and FastAPI runs the backend on `8000` by default. The frontend uses the Vite proxy to forward `/api` requests to the backend.

### When do I need to start ComfyUI first?

Only tools using the `comfyui` Provider require it. OpenAI Images-compatible tools do not depend on local ComfyUI.

### What if the workflow JSON upload does not detect the positive prompt node?

Make sure the file is a ComfyUI API workflow JSON file, then fill in the positive prompt node/input manually or edit the `prompt.positive` binding directly. The common input name is `text`.

### Does image generation overwrite old candidate images?

No. Image generation appends new candidates and keeps old images for comparison and manual selection.

### Does pausing image generation interrupt the current ComfyUI task?

No. Pause only stops later pages from being submitted to ComfyUI. The current submitted page continues to completion and its result is saved.

### DeepSeek reports an API key error. What should I check?

Open the Settings page and confirm the active DeepSeek configuration has an API key saved.

Do not write a real key into source code or commit it to Git.

## Development Status

Comaic is currently an MVP. The core pipeline works, and there is plenty of room to extend it:

- More reliable task recovery and progress reconnection
- Better migration rollback and backup tooling
- Richer ComfyUI workflow parameter injection
- Resume support for image generation
- Permissions, project export, and deployment improvements

You are welcome to use this project as a base for further experiments in AI-assisted comic creation.

### Workspace UX validation without generation services

From `frontend/`, run `node --test tests/*.test.cjs` for stream isolation, exact task navigation, refreshed background status and preparation requirements. Run `python -B frontend/tests/mock_workspace_api.py --port 8000` from the repository root alongside the frontend development server for 1280×720, 1440×900 and narrow-screen checks. The mock uses in-memory fixtures and simulated reference-image tasks, never calls real generation services or reads the real database, and discards uploads and edits on exit. Main actions stay near the top and technical settings are collapsed. Background Tasks refreshes when opened and shows update times; legacy records without locators open their project task list.
