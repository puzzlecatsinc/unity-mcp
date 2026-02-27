# OpenClaw x Coplay Unity MCP — VNext Draft Plan

**Date:** 2026-02-27  
**Last updated:** 2026-02-27 (Phase 1 audit reconciliation)  
**Base repo:** `CoplayDev/unity-mcp`  
**Base commit (local clone):** `08b8eac`  
**Goal:** Build a Unity MCP stack that can (1) run robust AI-driven QA gameplay loops and (2) perform reliable in-editor + in-game design operations.

---

## Phase 1 Status: ⛔ NOT READY — Hardening Required

Phase 1 code exists on two feature branches (`feat/phase1-snapshot-ref`, `feat/phase1-wait-primitives`) but has **5 confirmed blockers** that must be resolved before merge to `main` or proceeding to Phase 2.

See [§Phase 1 Hardening Gates](#phase-1-hardening-gates) below for the complete list and acceptance criteria.

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

- New tool: `scene_snapshot_capture` (implemented on `feat/phase1-snapshot-ref`)
  - returns compact hierarchy graph with stable refs (`uRef`)
  - ⚠️ **Blocker:** No C# handler wired — see hardening gate H-1
- New tool: `scene_snapshot_diff` (implemented on `feat/phase1-snapshot-ref`)
  - compares revisions; returns changed/removed refs
  - ⚠️ Diff semantics need review — see hardening gate H-4
- New tool: `ref_resolve` (implemented on `feat/phase1-snapshot-ref`)
  - resolves `uRef` -> current object metadata, returns stale reason if invalid

### Ref format (actual implementation)
`uRef = <sceneName>:<instanceId>:<revision>` (3-part, not 4-part as originally drafted)

> **Note:** Original proposal was `<projectHash>:<sceneGuid>:<instanceId>:<revision>`. Implementation simplified to 3-part format. This is acceptable for single-project use; revisit if multi-project support is needed.

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

- `wait_for_editor_state` (implemented on `feat/phase1-wait-primitives`) ✅ server-side logic complete
- `wait_for_gameobject` (implemented on `feat/phase1-wait-primitives`)
  - ⚠️ **Blocker:** Contract mismatch with C# — see hardening gate H-2
- `wait_for_console` (implemented on `feat/phase1-wait-primitives`) ✅ server-side logic complete
- `wait_for_predicate` — **NOT IMPLEMENTED.** Deferred (not critical for Phase 1; editor_state/gameobject/console cover the key cases).

### Touch points
- `Server/src/services/tools/wait_for.py` (new — implemented)
- `Server/tests/integration/test_wait_for_tools.py` (new — implemented)
- `MCPForUnity/Editor/Services/Transport/TransportCommandDispatcher.cs` (not yet touched — optional cancel/deadline pass-through deferred)

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

---

## Phase 1 Hardening Gates

Phase 1 branches (`feat/phase1-snapshot-ref`, `feat/phase1-wait-primitives`) must pass ALL gates below before merging to `main` or starting Phase 2 work.

### H-1: `scene_snapshot_capture` C# handler missing ⛔ CONFIRMED

**Evidence:** `grep -rn "scene_snapshot_capture" --include="*.cs"` returns zero hits. The Python tool (`Server/src/services/tools/scene_snapshot.py`, function `_fetch_scene_hierarchy`) sends command `"scene_snapshot_capture"` to Unity via transport, but no C# class with `[McpForUnityTool("scene_snapshot_capture")]` or matching `HandleCommand` exists.

**Impact:** Tool will always fail at runtime — Unity will reject the unknown command.

**Fix required:**
- Create `MCPForUnity/Editor/Tools/SceneSnapshotCapture.cs` with `[McpForUnityTool("scene_snapshot_capture")]`
- Handler must traverse scene hierarchy and return `{ success: true, data: { sceneName, objects: [{ instanceId, name, path, parentInstanceId, active, layer, tag, components }] } }`
- Response contract must match what `_fetch_scene_hierarchy` and `SnapshotStore.ingest` expect
- Include `includeInactive`, `includeComponents`, `maxNodes`, `rootInstanceId` parameter support

**Acceptance:** Integration test calling `scene_snapshot_capture` against a live Unity editor returns valid hierarchy.

---

### H-2: `wait_for_gameobject` contract mismatches ⛔ CONFIRMED

**Evidence (two sub-issues):**

**(a) `instanceIDs` vs `instanceIds` casing:**
- C# `FindGameObjects.cs` line 79: returns `instanceIDs` (capital D-S)
- Python `wait_for.py` line ~204: reads `resp_data.get("instanceIds")` (lowercase d-s) — **will never match**
- Also tries `resp_data.get("results")` which doesn't exist in the response either

**(b) `manage_gameobject:get_info` action does not exist:**
- Python `wait_for.py` line ~210: sends `{"action": "get_info", "instanceId": obj_id}` to `manage_gameobject`
- C# `ManageGameObject.cs` switch statement (lines 93-103) handles: `create`, `modify`, `delete`, `duplicate`, `move_relative`, `look_at` — no `get_info`
- Will hit `default:` and return `"Unknown action: 'get_info'"`

**Impact:** `wait_for_gameobject` will never detect object existence (key mismatch), and active/component checks will always fail (missing action).

**Fix required:**
- (a) Change Python to read `resp_data.get("instanceIDs")` to match C# response
- (b) Either add `get_info` action to `ManageGameObject.cs`, OR use the `unity://scene/gameobject/{id}` resource endpoint instead, OR use `find_gameobjects` with `includeInactive=True` + a new detail-fetch approach

**Acceptance:** `wait_for_gameobject("MainCamera", exists=True, active=True, component="Camera")` succeeds against live Unity.

---

### H-3: `SnapshotStore` singleton not instance-scoped ⚠️ CONFIRMED

**Evidence:** `SnapshotStore` (`Server/src/services/snapshot/snapshot_store.py`) uses a class-level `_instance` singleton. `get_instance()` returns the same store regardless of which Unity editor instance is active. Multiple connected editors would corrupt each other's ref graphs.

**Impact:** Multi-instance scenarios (which the base repo explicitly supports via `set_active_instance`) will produce incorrect refs.

**Fix required:**
- Key the store by `unity_instance` identifier (e.g., `dict[str, SnapshotStore]`)
- Pass `unity_instance` through from `scene_snapshot_capture` and `ref_resolve`
- `scene_snapshot_capture` already calls `get_unity_instance_from_context(ctx)` — wire it through

**Acceptance:** Two Unity instances connected → snapshots from instance A are isolated from instance B.

---

### H-4: Ref graph memory growth + diff semantics ⚠️ CONFIRMED (PARTIAL)

**Evidence:**
- `RefGraph._entries` grows monotonically — new uRef per object per revision, old entries never pruned (`ref_graph.py` `ingest_snapshot` lines 133-165). `SnapshotStore.max_history=50` trims revision metadata but not graph entries.
- Diff `potentially_removed` logic (`ref_graph.py` lines 182-189) has false-positive risk: checks `last_seen_revision` but that field is only set on newly-created entries in `ingest_snapshot`, not updated on existing entries for the same instanceId.

**Impact:** Memory leak over many snapshots (100+ snapshots × 2000 objects = 200K+ orphaned entries). Diff results may incorrectly report objects as removed.

**Fix required:**
- Add entry pruning: when a new entry supersedes an old one for the same `instanceId`, remove the old entry from `_entries`
- OR add a bounded eviction policy (e.g., prune entries not seen in last N revisions)
- Fix diff: track `last_seen_revision` on existing entries when their instanceId appears in a new snapshot

**Acceptance:** After 100 snapshots of a 500-object scene, `entry_count` stays bounded (not 50,000). Diff correctly identifies removed vs. still-present objects.

---

### H-5: Plan/docs drift ⚠️ CONFIRMED

**Evidence (now fixed in this commit):**
- Plan used dot-notation names (`scene_snapshot.capture`, `wait_for.editor_state`) — code uses underscores (`scene_snapshot_capture`, `wait_for_editor_state`)
- Plan uRef format was 4-part (`<projectHash>:<sceneGuid>:<instanceId>:<revision>`) — code is 3-part (`<sceneName>:<instanceId>:<revision>`)
- Plan listed `wait_for.predicate` — not implemented and not needed for Phase 1
- Plan listed touch points (e.g., `GameObjectSerializer.cs`, `ManageScene.cs`) that were not actually modified

**Status:** ✅ Resolved in this commit. API names, uRef format, and implementation status now match code.

---

### Phase 1 Merge Criteria (all must pass)

| Gate | Status | Blocking Phase 2? |
|------|--------|--------------------|
| H-1: C# handler for scene_snapshot_capture | ⛔ Not started | Yes |
| H-2a: instanceIDs casing fix | ⛔ Not started | Yes |
| H-2b: get_info action or alternative | ⛔ Not started | Yes |
| H-3: Instance-scoped snapshot store | ⚠️ Not started | Yes (for multi-instance) |
| H-4: Memory bounds + diff fix | ⚠️ Not started | Soft (ok for initial merge with known limitation) |
| H-5: Docs alignment | ✅ Done | No |

**Phase 2 gate:** H-1, H-2a, H-2b must be resolved. H-3 should be resolved. H-4 can be deferred with a TODO but must be addressed before production use.

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

### Snapshot (implemented on `feat/phase1-snapshot-ref`)
- `scene_snapshot_capture(scope="active"|"subtree", root_ref?, include_inactive?, include_components?, max_nodes=2000)`
- `scene_snapshot_diff(from_revision, to_revision?)`
- `ref_resolve(ref)`

### Wait (implemented on `feat/phase1-wait-primitives`)
- `wait_for_editor_state(is_playing?, is_paused?, is_compiling?, timeout_seconds=30, poll_interval_seconds=0.5)`
- `wait_for_gameobject(selector, search_method?, exists=true, active?, component?, timeout_seconds=30, poll_interval_seconds=0.5)`
- `wait_for_console(text?, text_gone?, level?, timeout_seconds=30, poll_interval_seconds=0.5)`

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

## 8) Immediate next actions

### Phase 1 hardening (current priority)

1. **H-1: Create `SceneSnapshotCapture.cs`** — C# handler that traverses scene hierarchy and returns structured object list. Branch: `feat/phase1-snapshot-ref`.
2. **H-2: Fix `wait_for_gameobject` contract** — (a) fix `instanceIDs` casing in Python, (b) add `get_info` action to `ManageGameObject.cs` OR switch to resource-based detail fetch. Branch: `feat/phase1-wait-primitives`.
3. **H-3: Instance-scope `SnapshotStore`** — key by `unity_instance` string. Branch: `feat/phase1-snapshot-ref`.

### After hardening passes
4. Merge both feature branches to `main` via PR.
5. Run integration tests against live Unity editor.
6. Begin Phase 2 (Runtime bridge alpha).

---

## 9) Notes for implementation style

- Keep one canonical code path per feature (no fallback complexity unless explicitly needed).
- Prefer additive modules over invasive rewrites for first iteration.
- Ship with integration tests per workstream before scaling tool surface.
- For long-running commands, always provide async status polling APIs.
