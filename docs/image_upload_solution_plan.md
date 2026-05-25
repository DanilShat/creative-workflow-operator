# Image upload to Gemini / Freepik — the right way

Compiled 2026-05-21 after the live run showed Claude trying to attach
files but stalling on Windows Explorer / the OS file picker.

## What the designer observed

When the worker starts Gemini, Claude clicks the composer's attach
control → that pops the **OS file-picker dialog** (Windows Explorer) →
Claude can't drive that dialog because it's outside the browser DOM and
outside `claude-in-chrome`'s scope → Claude retries, eventually times out.

The clipboard-paste fallback (`SetFileDropList` → `Ctrl+V`) also doesn't
land — Gemini's composer doesn't reliably accept file-drop paste; it
treats it as no-op (or, in some cases, sends the file path as text).

## Root cause

We've been writing **human-style instructions** ("click the paperclip,
then paste, then…") into a model that has a **first-class tool** for
exactly this job — and not telling it.

Looking at the Claude CLI init payload from my earlier diagnostic run,
`claude-in-chrome` exposes:

```
mcp__claude-in-chrome__file_upload
mcp__claude-in-chrome__upload_image
mcp__claude-in-chrome__form_input
mcp__claude-in-chrome__computer
mcp__claude-in-chrome__navigate
…
```

These are **the** programmatic file-attach tools — they bypass the OS
file picker entirely by setting the file input's `.files` property via
Chrome DevTools, the same way a real form upload happens under the hood.
Our prompt has been actively steering Claude away from them in favor of
clipboard hacks.

## The fix

Replace the clipboard-paste + click-attach choreography in
`gemini_prompt.py` and `freepik_image.py` with a single sentence per
image:

> "Use the `mcp__claude-in-chrome__file_upload` (or `upload_image`) tool
> to attach the file at `<absolute-path>` to the composer."

Concrete code-level changes (small, all in the worker):

1. **`_build_task` in both flows**: drop the entire clipboard-paste
   block. Replace it with a numbered "uploads" section that lists each
   absolute path and instructs Claude to use the upload tool with that
   path.
2. **Drop the `Bash` allowed tool** for Gemini — no more PowerShell
   clipboard tricks needed. Freepik still needs it for the
   PowerShell-move step at the end (or we replace that with the same MCP
   download flow if available; out of scope for this change).
3. **Stop the `--allowedTools` allow-list from being too narrow.** Add
   the chrome MCP namespace explicitly so Claude doesn't have to choose
   another path. e.g.
   `--allowedTools "Read,mcp__claude-in-chrome__*"`
   (verify the wildcard syntax with this Claude Code version; the
   alternative is to enumerate the half-dozen browser tools by name).
4. **Bump max_turns slightly down** for Gemini — without the clipboard
   round-trip per image, 40 should be plenty (saves cost and rate-limit
   pressure).
5. **Capture the result** — the file_upload tool returns a confirmation
   event in the stream; our existing transcript capture picks it up.

## What the new instruction looks like (sketch)

```
Step 1. Navigate to <gemini-url> in a new tab.

Step 2. Attach the following reference images to the composer using the
        mcp__claude-in-chrome__file_upload tool. Wait for each thumbnail
        to appear before doing the next one:

        - PACKSHOT: C:\…\packshot.png
        - REFERENCE: C:\…\style1.png

Step 3. Type the following brief into the composer verbatim — no opener,
        no preamble, no Freepik mention:

        <brief>

Step 4. Submit and wait for the Gem's reply.

Step 5. Return ONLY the Gem's reply text.
```

That's about a third the length of the current prompt, and it sidesteps
both the OS-file-picker dead end and the clipboard-paste reliability
issue.

## Alternatives, ranked

1. **The above (use `file_upload`)** — direct, supported, what the tool
   was built for. **Recommended.**
2. **Drag-and-drop dispatch via `javascript_tool`** — fabricate a
   `DataTransfer` and dispatch `drop` to Gemini's drop zone via the MCP
   JS tool. Brittle and Gemini-specific.
3. **Hit the Gemini API directly** with images as inline parts, skip the
   Gem UI entirely. Costs API tokens, loses the Gem's tuned system
   prompt. Big architectural detour.
4. **Vision-describe-then-text-only**: pre-pass each ref through a small
   vision model, embed the description into the brief, keep Gemini's
   composer text-only. Loses fidelity (descriptions aren't pixels).

## Risk on option 1

- Wildcard syntax for `--allowedTools` may differ between Claude Code
  versions; if `mcp__claude-in-chrome__*` doesn't take, enumerate the
  needed tools explicitly. The transcript stderr capture (already
  shipped) will surface "tool not permitted" if we get this wrong.
- The `file_upload` tool may need a selector argument (which `<input
  type="file">` to target). If so, the prompt should hint Claude to
  inspect the composer first or just let Claude figure it out from the
  page text — it has `get_page_text` and `find` tools available.
- The file_upload tool needs the local file path accessible to Claude
  (which it is — same `temp/jobs/.../inputs/` paths we already pass).

## Suggested commit

One small worker commit:

- Rewrite the upload block in both `_build_task` methods.
- Update `--allowedTools` to include the chrome MCP tools.
- Drop the Bash dependency in Gemini (Freepik keeps it for now).
- Adjust max_turns down a notch since the per-image cost falls.
- Update the unit tests for the prompt content (they currently assert
  `SetFileDropList`-style copy; assert the new `file_upload`-style
  instead).

Probably 30–60 lines net delta; high signal-to-noise change.

## Open question for the designer

Once this lands, the next live run is the truth-teller. If the
`file_upload` tool also stalls (unlikely but possible — e.g. Gemini's
file input is hidden behind a custom control that Chrome devtools can't
target), we'll see exactly where in the transcript: the tool will return
an error event rather than just hanging.
