# First vertical slice — Gate A

The first real MVP proof is not DCC. It is the browser E2E path:

`server task -> local LLM orchestration -> Gemini browser prompt-builder -> Freepik browser generation -> artifact upload -> human review -> retry`

## Required passing evidence
- Worker registers with token.
- Worker heartbeats every 15s.
- Gemini and Freepik profiles are authenticated.
- Task is created in UI with reference upload.
- Reference asset stored on disk and DB metadata recorded.
- Gemini job produces structured prompt output.
- Freepik job downloads real generated file.
- Worker uploads generated and debug artifacts.
- Server records prompts, runs, jobs, assets.
- Workflow enters server-side `waiting_human_review`.
- Worker returns to idle before human review.
- Reject creates new retry job.
