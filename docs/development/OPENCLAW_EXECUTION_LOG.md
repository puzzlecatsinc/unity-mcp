# OpenClaw Unity MCP — Execution Log & Operating Principles

**Date:** 2026-02-27  
**Repo:** `puzzlecatsinc/unity-mcp` (fork of `CoplayDev/unity-mcp`)  
**Scope:** What was completed, what principles we are enforcing, and what remains next.

---

## 1) What we completed

## A. Fork/bootstrap + branch structure

- Fork target: `git@github.com:puzzlecatsinc/unity-mcp.git`
- Remotes wired:
  - `origin` → Puzzle Cats fork
  - `upstream` → Coplay upstream
- Core branches established and pushed:
  - `main` (integration branch)
  - `upstream-beta` (mirror of upstream dev line)
  - `upstream-main` (mirror of upstream stable line)
  - `feature/openclaw-vnext-plan` (planning/documentation branch)

## B. Planning + sync strategy docs (on `feature/openclaw-vnext-plan`)

Committed:
- `24544c3` — `docs/development/OPENCLAW_VNEXT_PLAN.md`
- `80fb103` — `docs/UPSTREAM_SYNC.md` + `scripts/sync-upstream.sh`
- `e2ec373` — sync script/doc corrections
- `334687a` — Phase 1 audit reconciliation + hardening gates

## C. Phase 1 implementation branches

### Snapshot/Ref branch
- Branch: `feat/phase1-snapshot-ref`
- Commits:
  - `1880944` — initial Snapshot + RefGraph foundation
  - `5e4b6f8` — hardening fixes (C# handler, scoping/diff/memory corrections)
- Key files added/updated in latest hardening commit:
  - `MCPForUnity/Editor/Tools/SceneSnapshotCapture.cs`
  - `Server/src/services/snapshot/ref_graph.py`
  - `Server/src/services/snapshot/snapshot_store.py`
  - `Server/src/services/tools/scene_snapshot.py`
  - `Server/src/services/tools/ref_resolve.py`
  - `Server/tests/test_ref_graph.py`
  - `Server/tests/integration/test_scene_snapshot_tools.py`

### Wait primitives branch
- Branch: `feat/phase1-wait-primitives`
- Commits:
  - `9debdd2` — initial wait tools (`editor_state`, `gameobject`, `console`)
  - `0037c18` — contract hardening (`instanceIDs`, supported detail path, tests)
- Key files updated in latest hardening commit:
  - `Server/src/services/tools/wait_for.py`
  - `Server/tests/integration/test_wait_for_tools.py`

## D. Independent audits + adjudication loop

- Codex xhigh audit issued a **FAIL** for Phase 1 readiness due to concrete contract/runtime blockers.
- Opus adjudication reviewed those findings and updated plan docs with explicit **Phase 1 hardening gates**.
- Hardening implementation was then executed and pushed on both Phase 1 branches.

This is the intended quality loop:
1. Implement
2. Independent audit
3. Adjudicate findings
4. Update plan/gates
5. Fix and re-validate

---

## 2) Principles we are enforcing

1. **Upstream-first architecture**
   - Keep fork syncable; avoid unnecessary divergence.

2. **Additive over invasive changes**
   - Prefer new files/modules and narrow integration points.

3. **Contract fidelity over mocked success**
   - Tool contracts must match Unity/C# responses exactly (`instanceIDs`, supported actions, etc.).

4. **Instance-safe state**
   - No global cross-instance data structures for MCP runtime state.

5. **Deterministic behavior**
   - Explicit timeout/poll semantics; deterministic diffing and error modes.

6. **Evidence-first quality gates**
   - Tests + concrete command output required before calling work done.

7. **Execution hygiene**
   - Explicit file staging only (no `git add -A` / `git add .`).
   - Keep branch purpose clear (plan vs implementation).

8. **Plan-doc alignment**
   - If implementation deviates, docs must be corrected immediately.

---

## 3) Current branch map (authoritative)

- `feature/openclaw-vnext-plan` → planning, governance docs, hardening gates
- `feat/phase1-snapshot-ref` → snapshot/ref implementation + hardening
- `feat/phase1-wait-primitives` → wait implementation + hardening
- `main` → integration baseline (tracking upstream beta line)

---

## 4) Test evidence status (reported by implementation runs)

- Snapshot branch hardening run:
  - targeted + broader `Server` pytest passes reported (green)
- Wait branch hardening run:
  - targeted + broader `Server` pytest passes reported (green)

> Note: Unity Editor runtime compile/play-mode validation for new C# tool wiring still requires Unity-side execution environment and should be part of merge validation.

---

## 5) Immediate next steps

1. **Cross-branch validation in Unity Editor**
   - Verify `scene_snapshot_capture` works end-to-end against live Unity session.

2. **Integrate Phase 1 branches**
   - Merge `feat/phase1-snapshot-ref` and `feat/phase1-wait-primitives` into integration branch with final regression run.

3. **Begin Phase 2 only after Phase 1 gates pass**
   - Runtime bridge + trace/replay work starts only after contract and integration gates are green.

---

## 6) Quick command references

```bash
# sync upstream changes
./scripts/sync-upstream.sh

# stable-only sync
./scripts/sync-upstream.sh --stable

# dry-run sync
./scripts/sync-upstream.sh --dry-run

# inspect phase branches
git log --oneline origin/feat/phase1-snapshot-ref -n 5
git log --oneline origin/feat/phase1-wait-primitives -n 5
```
