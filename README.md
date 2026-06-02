# Comaic

English | [简体中文](./README.zh-CN.md)

comaic is a local-first AI comic generation workspace. It turns the workflow “story outline -> page scripts -> text-to-image prompts -> ComfyUI image generation -> manual image selection” into an operable MVP pipeline for experimenting with AI-assisted comic creation.

The current version is not designed to automate every creative decision. Instead, each key artifact remains reviewable and editable: outlines are shaped through multi-turn conversations, page scripts can be edited manually, image prompts can be regenerated, and ComfyUI candidate images can be selected page by page.

## Features

- Project management: create, edit, and delete comic projects.
- Outline workspace: run multi-turn conversations with the Outline Agent, stream replies in real time, and save outline versions.
- Page scripts: generate comic page scripts from an outline version, with batch generation, pause, section deletion, and manual editing.
- Image prompts: manage reusable “script to image prompt” system prompts and generate image prompts for completed script tasks.
- Image generation: manage ComfyUI workflow presets and generate candidate images from page image prompts.
- Manual selection: choose the final image for each page.
- Multilingual frontend: Chinese and English are currently supported.

## Tech Stack

- Backend: Python, FastAPI, LangChain, DeepAgents, SQLAlchemy, SQLite, SSE
- LLM: DeepSeek OpenAI-compatible API
- Frontend: Vue 3, Vite, Element Plus, vue-i18n
- Image generation: local ComfyUI HTTP API

## Project Structure

```text
comaic/
├── backend/      # FastAPI + LangChain + SQLAlchemy
├── frontend/     # Vue 3 + Vite + Element Plus
├── data/         # Local SQLite development data
├── outputs/      # Saved ComfyUI generated images
├── workflows/    # Optional local workflow_api.json backups
├── start.sh      # Local script that starts backend and frontend together
├── README.md
├── README.zh-CN.md
├── AGENTS.md
└── .gitignore
```

## Requirements

- Python 3.12
- Node.js 20.19+ or 22.12+
- npm
- Conda, with the recommended environment name `lang_graph`
- Local ComfyUI, default URL: `http://127.0.0.1:8188`
- DeepSeek API key

## Quick Start

### 1. Clone the repository

```bash
git clone <your-repo-url> comaic
cd comaic
```

### 2. Create and activate the Python environment

```bash
conda create -n lang_graph python=3.12
conda activate lang_graph
```

### 3. Install backend dependencies

```bash
pip install -r backend/requirements.txt
```

### 4. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### 5. Configure environment variables

Create a local `.env` from the example file:

```bash
cp backend/.env.example .env
```

Edit `.env`:

```env
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=your_deepseek_api_key

DATABASE_URL=sqlite:///data/comaic.sqlite3
COMFYUI_BASE_URL=http://127.0.0.1:8188
```

Do not commit your real `.env` file.

### 6. Start ComfyUI

Start your local ComfyUI server using the official ComfyUI workflow and make sure it is reachable in a browser:

```text
http://127.0.0.1:8188
```

### 7. Start comaic

The recommended local command starts both backend and frontend:

```bash
./start.sh
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

Open the “Projects” page, click “New Project”, and enter a project title.

A project is the creative container. Outlines, scripts, image prompts, and image generation tasks are all associated with a project.

### 2. Generate an outline

Open the “Outline Workspace”:

1. Select a project.
2. Create or reuse an outline session.
3. Chat with the Agent to refine genre, protagonist, setting, conflict, ending direction, and other story information.
4. After each turn, if the Agent decides the outline should be updated, a new outline version is saved on the right.

Outline versions are used as input for page script generation.

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

After generation, you can view, edit, clear, or delete page scripts. Batch generation can be paused, and generated content is kept after pausing.

### 4. Generate image prompts

Open the “Image Prompts” page:

1. Manage the “script -> text-to-image prompt” system prompt presets.
2. Select a project.
3. Select a completed script generation task.
4. Select a system prompt preset.
5. Start generation.

The system converts each structured page script into a positive prompt suitable for text-to-image generation and saves it to the page data. Regenerating image prompts for the same script task first clears that task’s existing image prompts, then streams the new results into the page.

### 5. Configure a ComfyUI workflow

Open the “Image Generation” page and create a workflow preset first.

The workflow preset must use ComfyUI API workflow JSON, not the regular visual workflow export. You can:

- Paste workflow API JSON directly.
- Drag and drop or choose a `.json` file.
- Use “Parse Positive Node” to automatically detect the positive prompt node ID and input name.

At minimum, configure:

- Workflow JSON
- Positive prompt node ID
- Positive prompt input name, commonly `text`

Seed node configuration is optional. If no seed node is configured, comaic does not force-inject a seed and uses the workflow’s own configuration.

### 6. Generate images

Open the “Image Generation” page:

1. Select a project.
2. Select a completed script task.
3. Select a workflow preset.
4. Set candidate count per page and polling interval.
5. Start generation.

Batch image generation currently submits one ComfyUI `/prompt` request per page. The backend polls `/history/{prompt_id}`, downloads generated images through `/view`, and stores them under `outputs/`.

Regeneration does not delete old images. It appends new candidate images so that you can compare and choose manually. Pausing image generation only stops submitting subsequent pages; it does not interrupt the currently submitted ComfyUI task.

### 7. Select final images

After candidate images are generated, inspect thumbnails in the “Image Generation” page and select one final image for each page.

## ComfyUI Workflow Notes

comaic does not ship with a fixed ComfyUI workflow. You maintain your own workflow presets in the UI.

Recommended workflow:

1. Build a text-to-image workflow in ComfyUI.
2. Export the API workflow JSON.
3. Add a workflow preset in comaic’s “Image Generation” page.
4. Drag in the JSON file or paste the JSON content.
5. Confirm the positive prompt node ID and input name.
6. Save the preset and use it for image generation.

If the workflow contains multiple `CLIPTextEncode` nodes, the frontend tries to avoid nodes that look like negative prompts, but you should still check the selected node manually.

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

comaic is still an MVP and does not use a formal migration tool for the local SQLite database. If ORM schema changes make your old local database incompatible, delete it and restart:

```bash
rm data/comaic.sqlite3
./start.sh
```

Time fields are stored as UTC ISO8601 strings with `+00:00` and displayed in the browser’s local timezone. If you upgrade from an older version, delete and rebuild the old local SQLite database.

Back up the database first if it contains important data.

## FAQ

### What is the relationship between frontend port 5173 and backend port 8000?

Vite runs the frontend on `5173` by default, and FastAPI runs the backend on `8000` by default. The frontend uses the Vite proxy to forward `/api` requests to the backend.

### Why do I need to start ComfyUI first?

The image generation stage calls the local ComfyUI HTTP API. If ComfyUI is not running, image generation requests will fail.

### What if the workflow JSON upload does not detect the positive prompt node?

Make sure the file is a ComfyUI API workflow JSON file, then fill in the positive prompt node ID and input name manually. The common input name is `text`.

### Does image generation overwrite old candidate images?

No. Image generation appends new candidates and keeps old images for comparison and manual selection.

### Does pausing image generation interrupt the current ComfyUI task?

No. Pause only stops later pages from being submitted to ComfyUI. The current submitted page continues to completion and its result is saved.

### DeepSeek reports an API key error. What should I check?

Check that the root `.env` file contains:

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
```

Do not write a real key into source code or commit it to Git.

## Development Status

comaic is currently an MVP. The core pipeline works, and there is plenty of room to extend it:

- More reliable task recovery and progress reconnection
- Formal database migrations
- Richer ComfyUI workflow parameter injection
- Resume support for image generation
- Permissions, project export, and deployment improvements

You are welcome to use this project as a base for further experiments in AI-assisted comic creation.

