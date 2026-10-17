# Dreamina Draft Executor (local MVP)

Small loopback-only Python service that removes repetitive CLI orchestration for storyboard drafts. It does **not** modify the existing result manager/UI and has no generation, quote, credit-confirmation, delete, upload, or arbitrary-command endpoint.

## Start

Double-click `start.cmd`, or run `./start.ps1` in PowerShell. Stop the service with `Ctrl+C`. Default bind is `127.0.0.1:8770`; the service refuses non-loopback binds, rejects non-local Host/Origin headers, and does not enable CORS. It is intended for local agent/CLI use, not the browser; do not port-forward it.

## API

Send JSON bodies from a local client. A plan is sent directly as JSON; the service never opens an arbitrary filesystem path.

- `GET /health` — CLI version and login status.
- `POST /v1/validate` — body `{"plan": <plan>}`; validates IDs, exact prompt first line, fixed video settings, 4–15 second duration, prompt/ref consistency, and no generation.
- `POST /v1/inspect` — body `{"projectId":"<uuid>","nodeIds":["node_..."]}`; one batched readback, redacted to stable facts and prompt hashes.
- `POST /v1/save` — body `{"plan": <plan>}`. Saves only; reads all targets first, skips exact already-verified drafts, blocks generated/running outputs, writes one-by-one with stable IDs and reads each back. If an existing draft has content, an explicit `allowOverwrite:true` is required; changed baseline conflicts otherwise stop the batch.

Example PowerShell (paste the token printed by the service):

```powershell
$headers = @{}
Invoke-RestMethod 'http://127.0.0.1:8770/health' -Headers $headers
$plan = Get-Content '.data\episode-plan.json' -Raw | ConvertFrom-Json
Invoke-RestMethod 'http://127.0.0.1:8770/v1/validate' -Method Post -Headers $headers -ContentType 'application/json' -Body (@{plan=$plan} | ConvertTo-Json -Depth 40)
```

## Safety and recovery

- Only typed CLI methods are implemented; no endpoint accepts a command string. Save commands are constructed without `--run` or credit flags.
- Each write uses the plan's stable `nodeId` and `updateId`; before/after state is stored in `.data/draft-executor/<projectId>.json`.
- A timeout/unknown response is not automatically replayed. Inspect the same node, then resume only after resolving whether the save landed.
- Existing generated media is protected. This service never runs generation; use the official CLI flow after separate review/approval.
- It logs route/time only, not prompts, authorization headers, or full CLI output.

## Tests

`python -m unittest tests.test_draft_executor -v` uses a fake CLI and temporary state directory. No real canvas or generated media is touched.
