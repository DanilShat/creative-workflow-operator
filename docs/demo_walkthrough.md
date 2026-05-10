# Demo Walkthrough

1. The operator starts the Docker stack and opens the Streamlit dashboard.
   Screenshot: `docs/screenshots/streamlit_dashboard.png`.

2. A designer enters a brief and attaches a reference image in the UI.
   Screenshot: `docs/screenshots/streamlit_dashboard.png`.

3. Streamlit creates a task through FastAPI; FastAPI persists the task and
   reference metadata in PostgreSQL.
   Screenshot: `docs/screenshots/job_detail.png`.

4. The local LLM normalizes the brief into strict JSON and decides the Gate A
   route.
   Screenshot: `docs/screenshots/job_detail.png`.

5. FastAPI creates a queued browser job for the authenticated worker.
   Screenshot: `docs/screenshots/job_detail.png`.

6. The designer laptop worker heartbeats, polls, claims the job, and downloads
   input assets.
   Screenshot: `docs/screenshots/job_detail.png`.

7. Playwright opens the persistent Gemini profile and builds the prompt from
   the brief and references.
   Screenshot: `docs/screenshots/artifact_browser.png`.

8. Playwright runs the Freepik generation/download path and captures artifacts
   or debug evidence.
   Screenshot: `docs/screenshots/artifact_browser.png`.

9. The worker uploads generated files back to FastAPI, which stores artifact
   metadata and file bytes under the operator artifact root.
   Screenshot: `docs/screenshots/artifact_browser.png`.

10. The operator reviews the result in Streamlit, approves it, or rejects it
    with repair feedback that creates a retry job.
    Screenshot: `docs/screenshots/job_detail.png`.
