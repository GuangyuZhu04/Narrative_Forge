# Open Source Release Notes

This folder is a sanitized release copy of the project codebase for public/open-source use.

## What Is Included

- Backend source code, schemas, models, services, API routes, prompts, and tests.
- Frontend source code, public assets, package manifests, and TypeScript/Vite configuration.
- Project documentation under `docs/`.
- Example backend environment file at `backend/.env.example`.
- An empty `backend/data/.gitkeep` so the local SQLite directory exists on first run.

## What Was Removed

The release copy intentionally excludes local and user-specific artifacts:

- `.env` files and local secrets.
- SQLite databases such as `data/novel_agent.db`, `test_db.db`, and temporary debug databases.
- Uploaded character images and other runtime files under `data/uploads`.
- Backend and frontend logs.
- `node_modules`, frontend build output, Python caches, pytest/ruff caches, and generated egg metadata.
- Local manual-import drafts or debugging files that contain private novel material.

## First Run

Backend:

```bash
cd backend
cp .env.example .env
pip install -e .[dev]
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Before using AI features, open the app and add an LLM configuration. Do not commit `.env`, database files, uploaded images, or logs.

## Publishing Checklist

- Initialize a fresh Git repository inside this folder.
- Run `git status --ignored` and confirm ignored runtime data is not staged.
- Replace placeholder `SECRET_KEY` in any deployment environment.
- Review `LICENSE` and package metadata before publishing under your preferred project name.
