# Exec Dashboard Server

Python server that:
- serves the React/Vite UI static build from `exec_dashboard_ui/dist`
- exposes API endpoints backed by Vertica tables

## Endpoints

- `GET /api/health`
- `GET /api/dashboard/dataset?table=qa_kpi_agg_denorm&limit=4000`

## Run

From repo root:

```bash
source .venv/bin/activate
python exec_dashboard_server/server.py
```

The UI build should exist first:

```bash
cd exec_dashboard_ui
npm install
npm run build
```

Then open:

- `http://localhost:8000`
