# Next Round of Fixes — Gate A workflow

Compiled 2026-05-21 after watching `conv_bb2cd91baab54fec` fail end-to-end.

## What the debug asset confirmed

Both Freepik attempts died at exactly **26 turns** with `subtype: error_max_turns`:

```
attempt 1: duration_ms 127249,  output_tokens 5466,  total_cost $0.193
attempt 2: duration_ms 135021,  output_tokens 5521,  total_cost $0.191
```

Claude was *working* (5.5k output tokens, ~$0.19/run) — it ran out of turn
budget mid-Freepik. With `--max-turns 25` and `--allowedTools Bash,Read`,
every click / type / wait costs a turn, and Freepik needs many more than 25
(open URL → set aspect → type prompt → click Generate → wait 60-90s for
images → click download per image → PowerShell-move each file → report JSON).

We currently save only the final exit JSON as the debug asset. Without the
full turn transcript we can't see *which* step Claude was on when it ran out.
Fix #5 below makes the next failure debuggable.

---

## Designer-reported issues + my read

### 1. Reference images are never actually given to Gemini or Freepik

**Designer's report:** The packshot/style refs you attach in chat are stored
as assets, and the asset IDs are *mentioned* to Claude — but they're never
**uploaded into the Gemini Gem composer or the Freepik image generator**.
Gemini sees only text instructions and a list of opaque IDs; Freepik
gets the prompt but never the packshot reference image.

**Root cause:**
- `gemini_prompt.py._build_task` sends Claude a text instruction containing
  `Reference asset ids: <ids>` — meaningless to Gemini.
- `freepik_image.py._build_task` mentions a `source_asset_id` packshot but
  never tells Claude to upload it through Freepik's image-to-image control.
- The worker *does* download references to local disk via
  `WorkerAssetManager.download_inputs` → `temp/jobs/<job_id>/inputs/`, but
  the flow scripts don't surface those local paths to Claude.

**Fix (M):**
- In `gemini_prompt.py`, pass Claude the absolute local paths of the
  downloaded references and instruct it to upload them into the Gem composer
  via Gemini's "attach image" button.
- In `freepik_image.py`, when `source_asset_id` is set, pass Claude the
  packshot's local path and instruct it to use Freepik's image-to-image /
  reference upload control.
- **Open question:** verify the photo Gem actually accepts image uploads
  driven through the Chrome composer; if it only accepts text, we may need
  a Gemini Pro vision step that describes the refs first and feeds the
  description into the Gem.

### 2. Agent should ask which image is the packshot — even with one image

**Designer's report:** When images are attached, the orchestrator just
guesses the first one is the "packshot" (`source_asset_id`). Often the
packshot isn't image #1, or there *is no* packshot (refs are pure style).
The agent should always ask, and offer **None** so the designer can say
"these are all style references, no anchor product".

**Fix (L):**
- New conversation state: `pending_packshot_clarification`. After
  `_handle_gate_a` stores references and infers brief/title/output_type,
  *don't* immediately call `start_gate_a`. Instead post an agent bubble
  with image-button choices + a **None** button.
- New action type `select_packshot` with payload
  `{run_intent_id, choice: asset_id | "none"}`.
- Stash the staged intent (brief, output_type, variant_count, asset_ids)
  on the conversation (new column or a small table) until the click lands.
- On click, the orchestrator resumes by calling `start_gate_a` with
  `source_asset_id` set to the chosen asset (or `None`).
- UI: render the clarification bubble. Image-buttons send the
  `select_packshot` action.

### 3. Gemini "instruction prefix" is unwanted

**Designer's report:** The Gemini Gem we use is already configured with a
system prompt that knows it's preparing prompts for Freepik. The current
boilerplate
> "You are preparing a prompt for Freepik AI image generation. Return only
> the final prompt text, no markdown."
is redundant and could confuse the Gem (or just waste its budget).

**Fix (S):** In `gemini_prompt.py._build_task`, drop the lead boilerplate.
Send only: the designer's brief, operator note, packshot guidance, and (once
fix #1 lands) the uploaded reference images. The Gem's own system prompt
does the rest.

### 4. Surface more step detail in the chat

**Designer's report:** The chat shows only the big checkpoints
("Got it — starting Gate A" / "Prompt is ready" / "Image is ready"). You
want to see *what the worker is actually doing right now* — which Claude
turn, which step inside the flow.

**Fix (M), two paths — pick one:**
- **Operator-side narration (preferred):** the orchestrator already gets
  `POST /jobs/{id}/progress` events with `step` and `message`. When the
  `step` changes, append a *short* status line under the latest agent
  bubble (e.g. as an ephemeral child of the bubble, not a new message
  row — too noisy if persisted).
- **UI-only:** the console already polls `/history`. Render the latest
  `job_progress` event's `step` + `message` as an ephemeral status line
  under whichever agent bubble holds the active `related_run_id`. Zero
  backend change, just an extra render in `appendReviewPanel`/the active
  bubble.

### 5. Save the full Claude turn transcript (debugger's wish)

**My report:** When `error_max_turns` happens, the saved
`freepik_claude_result.txt` contains only the exit envelope, not the
per-turn tool calls. We can't see what Claude clicked, read, or got stuck on.

**Fix (S):** In `desktop_browser_flow.py._run_claude_browser_task`, switch
the CLI flags so the streaming JSONL of every tool call is captured, save
that to the debug asset alongside (or instead of) the final envelope. The
file lives 7 days under `DEBUG_TTL_7D` already — perfect for postmortems.

---

## Suggested rollout — what to ship first

These four fixes are small and unblock the rest:

1. **`--max-turns` per flow** — Gemini stays at 25, Freepik gets 80
   (`desktop_browser_flow.py`, single tuple change).
2. **Capture full Claude transcript** (#5).
3. **Strip the Gemini boilerplate prefix** (#3).
4. **Type `error_max_turns` as its own retryable failure** so the chat
   narration says "ran out of turns, retrying" instead of buying it under
   `download_failed`.

After that lands and we can actually see what Claude is doing, the bigger
pieces:

5. Real image upload into Gemini and Freepik (#1) — design pass first.
6. Packshot clarification flow (#2) — needs the staged-intent table.
7. Step streaming in the chat bubble (#4) — small, can go any time.

---

## Notes worth remembering

- The **Gemini prompt that this run produced was good** — preserved as
  `prompt_cb9e1f5…` in the DB. Reusable for testing the Freepik step
  in isolation without re-running Gemini.
- Each `error_max_turns` run still costs ~$0.19. The retry policy is doing
  its job by stopping at 2 attempts, but each attempt is currently pure
  waste. Fixing #1 above lets the same budget actually produce an image.
- Conversation `conv_bb2cd91baab54fec` is currently in `failed` state.
  No code path today lets the designer say "try again" from a failed run
  (LLM `retry_last` only handles `human_rejected`). When we tackle this
  batch, add a "failed → restart Gate A from the existing prompt" handler
  so the prompt isn't thrown away.
