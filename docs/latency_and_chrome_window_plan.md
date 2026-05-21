# Latency + Chrome-window regression — plan

Compiled 2026-05-21 after two real Gate A attempts that hung at the Gemini
image-upload step and a designer complaint that **send** in chat already
feels too slow before anything Gate-A even starts.

Two distinct problems, with deliberately separate diagnoses below — they
share no root cause but they share the same window of frustration.

---

## A. Regression: `claude --chrome` no longer opens its own window

**Designer report:** In earlier sessions `claude --chrome` would always
open a fresh Chrome window. After the image-paste instruction landed, no
window appears, no visible activity, the subprocess just sits silent until
the 300 s timeout.

**What I verified from this side:**
- The CLI itself is fine — a bare `claude --chrome -p --output-format stream-json --verbose --max-turns 3 "respond READY"` finished in 22 s on the laptop with a clean stream-json result.
- `claude-in-chrome` MCP reports `"status":"connected"` on init.
- The hung run produced **zero stdout** for 5 min — not even the `system/init` event was written to the transcript file, so the subprocess.run kill leaves us with nothing to debug.
- The laptop has **30+ Chrome processes** in the listing — accumulated zombies from prior runs are plausible but not proven to be the cause.

**Hypotheses, ordered most-likely first:**

1. **Stderr swallow.** Claude CLI prints MCP errors and warnings to stderr,
   not into the json stream. Our `subprocess.run` captures stderr but
   discards it on the success path; on the timeout path we lose stderr too
   (Python's `TimeoutExpired.stderr` IS available, but our code re-raises
   without reading it). So when the MCP is choking on the user's loaded
   Chrome (sign-in challenge, modal, locked tab), we never see the message.
2. **First-tool-call hang.** The first thing the new prompt tells Claude is
   to *prepare clipboards and navigate to the Gemini URL*. If the MCP's
   `navigate` tool blocks waiting for a tab settle that never comes
   (because that Chrome tab is in a weird state from a previous session),
   Claude waits indefinitely for the tool response. No further stdout.
3. **Prompt length / decision drift.** The new image-attach block is long.
   Smaller models may spend the first few turns "planning" silently before
   the first tool call. Less likely than the stderr issue but worth ruling
   out by capturing every turn even on hang.

### Steps to nail down the cause

1. **Capture stderr to a debug asset.** Add a second `transcript_path` in
   the worker for stderr, write it on both success and failure, upload it.
   This is the single most useful one-line investment because right now we
   are completely blind on hangs.
2. **Persist stdout DURING the subprocess, not after.** Today we hand
   `subprocess.run` capture_output and only read the buffer after it
   returns. On `TimeoutExpired` we re-raise without saving what came in. Read
   `exc.stdout` / `exc.stderr` from `TimeoutExpired` before re-raising, or
   switch to `Popen` + readline-into-file so the transcript exists live.
3. **Bare-Gemini-navigate sanity test** the next time the worker is up — a
   one-off task that just opens the photo Gem URL and answers READY. If
   that hangs identically, the MCP+Chrome is the root cause and image
   instructions are a red herring.

### Likely real fix once we see stderr

- Add an explicit **"Step 0: Use the navigate tool to open `<gemini-url>`
  in a new tab"** at the very top of the prompt so the model can't drift
  to "switch_browser" or reuse a loaded tab.
- Reduce `--max-turns` for an early-exit sanity check the first time the
  prompt runs — confirm Claude reaches the first tool call.
- If the MCP is the actual block, fall back to a tiny worker-side step that
  pre-opens Chrome to the URL via `Start-Process` before invoking Claude.

---

## B. Send latency — `POST /messages` is too slow

**Designer report:** Sending a chat (especially the first one with images)
makes the UI sit in "thinking…" too long. The first-image send and the
packshot-confirm click both feel sluggish.

**Where the time actually goes** (worst case, brief + 2 images + first message in a brand-new chat):

| step | typical cost | why |
|---|---|---|
| multipart upload | ~50–300 ms | network |
| sha256 + disk write per ref (× 2) | ~50–500 ms total | tiny image, fast disk |
| `llm.classify_chat_intent` (Ollama JSON-mode) | **3–10 s** | gemma3n:e2b call |
| `llm.auto_title` (first turn only) | **3–10 s** | another Ollama call |
| commit / event rows | ~50 ms | postgres |
| **return** | | |

So a first-message send pays **two serial Ollama calls**, ~6–20 s.

Then `confirm packshot` triggers `workflow.start_gate_a`, which calls:

| step | cost | why |
|---|---|---|
| `llm.normalize_brief` | **3–10 s** | |
| `llm.route_for_gate_a` | **3–10 s** | |
| create Run + Gemini jobs | ~50 ms | |

…**two more** serial Ollama calls before the worker is even told a job is
queued.

So every Gate-A run pays ~12–40 s of Ollama time in the chat layer
**before any actual image work starts**. With a tiny model these are short
but visible; if Ollama itself is loaded they're brutal.

### Optimizations, ordered by effort/reward

1. **Drop `normalize_brief` + `route_for_gate_a` entirely.** *(S, biggest win)*
   These were legitimate when Gate A was open-ended; today every chat-driven
   task takes the exact same path (Gemini prompt → Freepik image). Replace
   with a hardcoded `route="gemini_prompt_builder", capability="browser.gemini"`,
   delete the two Ollama calls. Saves 6–20 s on every confirm-packshot.
   The fallback in `LocalLLMService` already returns those exact values
   when Ollama is down, so this is a no-behavior-change refactor.

2. **Skip `classify_chat_intent` when attachments are present.** *(S)*
   An image + text in chat is unambiguously a Gate A request. Today we
   still ask the LLM to confirm. Just bail to the gate_a path directly
   and use the LLM only for title extraction. Saves 3–10 s on every
   image-attached send.

3. **Defer `auto_title` to a background task.** *(M)*
   Return the user_message / agent_message immediately with title
   `"Untitled"` (or the first-five-words heuristic we already have).
   Spawn the Ollama call in a thread / asyncio task that updates the
   Conversation row once the title is ready; the UI's 10 s sidebar poll
   picks the new title up automatically. Saves 3–10 s on every
   first-message send.

4. **Parallelize asset stores.** *(S, small but free)*
   `store_reference` for N attachments today is serial. Files are small,
   sha256 is fast, but disk writes can be done concurrently with
   `asyncio.to_thread`. Mostly cosmetic but cheap.

5. **Single one-shot Ollama call instead of two/four.** *(M)*
   Replace `auto_title` + `classify_chat_intent` + `normalize_brief` +
   `route_for_gate_a` with one prompt that returns `{title, intent, brief,
   output_type}` in one round-trip. Saves a few hundred ms of model warmup
   per call plus simplifies the orchestrator. Useful only if (1) above
   doesn't already kill the worst latency.

6. **Switch model selectively.** *(S, separate concern)*
   The `--model claude-haiku-4-5-20251001` flag in `desktop_browser_flow`
   is being ignored by Claude Code 2.1.139 — the live test showed the
   main loop running on `claude-sonnet-4-6` regardless. That's why our
   per-run cost is ~$0.19+ rather than the haiku price. Worth confirming
   the right flag name in this CLI version (likely `-m` or a config setting)
   and re-pinning, or accepting sonnet pricing and updating the doc.
   Also: we're at **84 % of the 7-day rate-limit utilization** as of the
   diagnostic run; each failed Gemini attempt costs ~$0.19 and pushes us
   closer. The latency wins above directly reduce that pressure.

### Suggested rollout

Two small commits, biggest impact first:

- **Commit 1** — items 1 + 2: drop the four redundant Ollama calls. Single
  file in the orchestrator + workflow, deleting code; minimal new tests
  (assert no Ollama call in the path); should immediately make
  send + confirm feel snappy.
- **Commit 2** — item 3 + the stderr/transcript-on-timeout investigation
  from §A. A bit larger; the background-title task needs a small thread or
  asyncio executor.

Items 4–6 are nice-to-have. Tackle after the user feedback on commits 1–2.

---

## What I'd NOT change yet

- The packshot clarification flow itself — that's the right shape; nothing
  in the latency profile is its fault.
- The image-attach instruction in the worker — once we capture stderr, we
  may find a tiny prompt change fixes the window regression; rewriting the
  whole approach blind is wasteful.
- The clipboard format (`SetFileDropList`) — we don't actually know whether
  this works yet because Claude never reached the paste step. Hold off
  until we see a transcript that reaches the paste turn.

---

## Open questions for the designer

1. After the next attempt, is the **same single Gemini job orphaned** again,
   or does it produce a transcript with at least an init event? If even
   the init event is missing, that's the stderr we have to capture.
2. Is the rate limit (84 % weekly) something you want to actively manage,
   or are we OK burning through it on diagnostics? It resets — but a few
   more failed runs and we'll hit a hard wall mid-test.
