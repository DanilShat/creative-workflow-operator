# Operator Console

A web console for running the creative workflow — gallery, brief composer, the live
Gate A pipeline (Gemini → Freepik), review/retry, chat, and worker status. It replaces
the old Streamlit dashboard.

It is a single self-contained page (`src/creative_workflow/server/ui/app/index.html`)
**served by the operator itself** — no build step, no Node, no separate install.

## Run it

The console is served by the operator server, so you just start the operator:

```powershell
cd creative_workflow_operator
# one-time: copy .env.server.example -> .env.server and fill it in
python -m creative_workflow.server.cli dev
```

Then open the URL it prints:

```
http://127.0.0.1:8000/app/
```

(`http://127.0.0.1:8000/` redirects there automatically.)

## Who opens it from where

The console is **not** an app you install on each machine — it is a page the operator
hosts, like a router admin page.

- **Operator + designer on one laptop** (single-laptop sandbox): open
  `http://127.0.0.1:8000/app/` in any browser on that laptop.
- **Separate machines**: the operator binds `0.0.0.0`, so from the designer laptop open
  `http://<operator-LAN-ip>:8000/app/`. Nothing to install on the designer side — just a
  browser bookmark. When the operator is updated, every browser sees the new UI.

The **worker** (browser automation on the designer laptop) is a separate process and is
unaffected by the console — it talks to the operator's `/api/v1/...` API as before.

## Screens

- **Gallery** — every task as a card with its workflow state; filter by state.
- **New brief** — title, brief, output type, drag-in reference images.
- **Task detail** — the live Gemini → Freepik → Review pipeline, generated prompt,
  image grid, and an activity timeline. Start Gate A, review, retry from here.
- **Chat** — message the local agent.
- **System** — operator health and connected workers.

## Notes

- **Reference uploads** hash files in the browser via the Web Crypto API, which needs a
  secure context. Open the console via `127.0.0.1` / `localhost` on the operator
  machine, or over HTTPS — a plain LAN-IP URL will block uploads (the app says so).
- The old Streamlit dashboard still works (`server ui`) as a fallback.
- New API endpoints backing the console: `GET /api/v1/tasks`, `GET /api/v1/workers`.
- This same HTML/JS is the frontend a Tauri desktop wrapper would use later, if a
  standalone `.exe` is ever wanted — no rewrite needed.
