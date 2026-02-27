# OpenClaw x Coplay Unity MCP — VNext Draft Plan

**Date:** 2026-02-27  
**Base repo:** `CoplayDev/unity-mcp`  
**Base commit (local clone):** `08b8eac`  
**Goal:** Build a Unity MCP stack that can (1) run robust AI-driven QA gameplay loops and (2) perform reliable in-editor + in-game design operations.

---

## 1) Why this base

We are using `CoplayDev/unity-mcp` as the starting point because it already has:

- mature transport split (stdio + HTTP)
- plugin <-> server WebSocket bridge (`/hub/plugin`)
- large tool/resource surface
- multi-instance support (`set_active_instance` + `unity_instances`)
- active community + maintenance velocity

Compared to our current OpenClaw Unity bridge, this is a better systems foundation. We should **extend this architecture**, not rewrite from scratch.

---

## 2) Core gaps to close for our end-goal

Current repo is strong for editor automation, but the QA/gameplay target needs these additions:

1. **Stable AI targeting model** (Playwright-like refs)
2. **Deterministic wait semantics** (not ad-hoc polling in prompts)
3. **Runtime bridge in player builds** (not editor-only control)
4. **Trace + replay artifacts** (for debugging/CI evidence)
5. **Scenario runner for autonomous QA loops**

---

## 3) Proposed architecture changes (draft)

## Workstream A — Snapshot + Ref Graph (must-have)

### Problem
Tool calls currently target by names/paths/IDs inconsistently. Agents can lose targets after hierarchy changes.

### Change
Introduce a first-class "snapshot state model" similar to Playwright:

- New tool: `scene_snapshot.capture`
  - returns compact hierarchy graph with stable refs (`uRef`)
- New tool: `scene_snapshot.diff`
  - compares revisions; returns changed/removed refs
- New tool: `ref.resolve`
  - resolves `uRef` -> current object metadata, returns stale reason if invalid

### Ref format (proposal)
`uRef = <projectHash>:<sceneGuid>:<instanceId>:<revision>`

### Touch points
- `Server/src/services/tools/` (new modules)
- `Server/src/services/resources/` (snapshot resource for read-only pull)
- `MCPForUnity/Editor/Helpers/GameObjectSerializer.cs` (emit stable fields)
- `MCPForUnity/Editor/Tools/ManageScene.cs` + `FindGameObjects.cs` (ref-aware output)

---

## Workstream B — Wait primitives (must-have)

### Problem
Agent loops are fragile when they manually poll logs/hierarchy without standardized wait contracts.

### Change
Add explicit synchronization tools:

- `wait_for.editor_state` (e.g., `isCompiling=false`, `isPlaying=true`)
- `wait_for.gameobject` (exists/active/component present)
- `wait_for.console` (error/warning text appears/disappears)
- `wait_for.predicate` (server-side polling with timeout + interval)

### Touch points
- `Server/src/services/tools/preflight.py` (shared wait helpers)
- `Server/src/services/tools/wait_for.py` (new)
- `MCPForUnity/Editor/Services/Transport/TransportCommandDispatcher.cs` (optional cancel/deadline pass-through)

---

## Workstream C — Runtime MCP bridge (must-have for gameplay QA)

### Problem
Editor control is not enough for true gameplay QA (device/runtime input, HUD, runtime-only systems).

### Change
Add runtime transport client in `Runtime/` that can connect to MCP server securely.

- Runtime registration: `kind = editor|runtime`
- Command routing supports target channel (`target":"runtime"`)
- Runtime-safe tools subset:
  - `runtime.get_state`
  - `runtime.input.*` (actions, taps, virtual controls)
  - `runtime.screenshot`
  - `runtime.object.find/get/set`
  - `runtime.console.get`

### Touch points
- `MCPForUnity/Runtime/` (new bridge service + DTOs)
- `Server/src/transport/plugin_registry.py` (session capability metadata)
- `Server/src/transport/plugin_hub.py` (targeted dispatch/editor-runtime routing)
- `Server/src/services/tools/` runtime tool modules

---

## Workstream D — QA trace + replay (must-have)

### Problem
No reliable forensic trail when autonomous runs fail.

### Change
Add run-scoped tracing:

- Every tool call tagged with `run_id`, `step_id`
- Persist:
  - command envelope
  - result
  - timestamps
  - optional screenshots
  - optional console deltas
- Export to JSONL + optional HTML summary

### Touch points
- `Server/src/core/` (trace service)
- `Server/src/services/tools/utils.py` (trace hook)
- new config flags in `Server/src/core/config.py`

---

## Workstream E — Scenario runner (must-have)

### Problem
Agent-level loops are currently implicit. We need deterministic orchestrations that can run in CI.

### Change
Add:

- `qa_scenario.run`
- `qa_scenario.status`
- `qa_scenario.cancel`

Scenario schema:
- steps with action + wait + assert
- retry policy
- artifact capture policy

### Touch points
- `Server/src/services/tools/qa_scenario.py` (new)
- `Server/src/models/` (scenario models)
- test coverage in `Server/tests/integration/`

---

## Workstream F — OpenClaw integration adapter (should-have)

### Goal
Keep compatibility with OpenClaw orchestration while leveraging Coplay architecture.

### Change
Add optional adapter mode:
- expose a thin OpenClaw-friendly endpoint/tool mapping
- preserve standard MCP for IDE clients

This prevents lock-in and lets Telegram/Discord automation use the same core.

---

## 4) MVP phase plan

### Phase 0 — Fork + wiring (1 day)
- create fork
- set `upstream` and `origin`
- create branch: `feature/openclaw-vnext-foundation`
- add this plan + ADRs

### Phase 1 — Snapshot/Ref + Wait (3-5 days)
- implement Workstreams A + B
- integration tests + sample prompts

### Phase 2 — Runtime bridge alpha (5-8 days)
- implement Workstream C (minimal runtime tool set)
- test in sample game build

### Phase 3 — QA trace + scenario runner (3-5 days)
- implement Workstreams D + E
- produce CI-compatible artifacts

### Phase 4 — OpenClaw adapter + hardening (2-4 days)
- implement Workstream F
- add docs + migration guide

---

## 5) Initial API draft (new tools)

### Snapshot
- `scene_snapshot.capture(scope="active"|"subtree", rootRef?, includeComponents=false, maxNodes=...)`
- `scene_snapshot.diff(fromRevision, toRevision)`
- `ref.resolve(ref)`

### Wait
- `wait_for.editor_state(isCompiling?, isPlaying?, timeoutSeconds=30)`
- `wait_for.gameobject(selector, exists=true, active?, component?, timeoutSeconds=30)`
- `wait_for.console(text?, textGone?, level?, timeoutSeconds=30)`

### Runtime
- `runtime.get_state()`
- `runtime.input.perform(action, value?)`
- `runtime.screenshot(mode="frame"|"camera")`
- `runtime.object.query(selector)`

### QA
- `qa_scenario.run(spec, trace=true)`
- `qa_scenario.status(runId)`
- `qa_scenario.cancel(runId)`

---

## 6) Acceptance criteria

1. Agent can reliably perform a 20+ step scene manipulation flow using refs only (no name-based drift).
2. Agent can run a gameplay smoke scenario in runtime build and return pass/fail + artifacts.
3. Every failed run includes trace bundle (JSONL + screenshots + console summary).
4. Works in both IDE MCP clients and OpenClaw-driven remote orchestration.

---

## 7) Risks and mitigations

- **Runtime security risk** -> runtime auth token + loopback defaults + explicit enable flags
- **Payload bloat** -> incremental snapshot diffs + paging defaults
- **Unity main-thread contention** -> dispatcher deadlines + cancellation + bounded queue
- **Cross-version Unity behavior** -> CI matrix across at least 2021 LTS + 2022 LTS + Unity 6

---

## 8) Immediate next actions (blocked + ready)

### Blocked (needs GitHub auth)
1. `gh auth login`
2. `gh repo fork CoplayDev/unity-mcp --remote=true`
3. Set remotes:
   - `origin` -> personal fork
   - `upstream` -> `CoplayDev/unity-mcp`

### Ready now
1. Open tracking issue set in fork (once created):
   - #1 Snapshot + Ref Graph
   - #2 Wait primitives
   - #3 Runtime bridge alpha
   - #4 Trace pipeline
   - #5 Scenario runner
2. Implement Phase 1 on feature branch.

---

## 9) Notes for implementation style

- Keep one canonical code path per feature (no fallback complexity unless explicitly needed).
- Prefer additive modules over invasive rewrites for first iteration.
- Ship with integration tests per workstream before scaling tool surface.
- For long-running commands, always provide async status polling APIs.
