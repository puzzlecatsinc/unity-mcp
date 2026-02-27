# Upstream Sync Strategy

**Fork of:** `CoplayDev/unity-mcp`  
**Purpose:** Extend with OpenClaw QA/runtime capabilities while staying current with upstream.

---

## 1. Remote Setup

```
origin    → git@github.com:<you>/unity-mcp.git   (our fork — push target)
upstream  → https://github.com/CoplayDev/unity-mcp.git  (read-only sync source)
```

### One-time setup (after fork exists)

```bash
# If origin still points to CoplayDev, fix it:
git remote rename origin upstream
git remote add origin git@github.com:<you>/unity-mcp.git

# Or if starting fresh after gh repo fork:
git remote add upstream https://github.com/CoplayDev/unity-mcp.git
git remote set-url origin git@github.com:<you>/unity-mcp.git

# Verify
git remote -v
# origin    git@github.com:<you>/unity-mcp.git (fetch)
# origin    git@github.com:<you>/unity-mcp.git (push)
# upstream  https://github.com/CoplayDev/unity-mcp.git (fetch)
# upstream  https://github.com/CoplayDev/unity-mcp.git (push)
```

---

## 2. Branch Policy

### Upstream tracking branches (never commit directly)

| Local branch     | Tracks              | Purpose                          |
|------------------|---------------------|----------------------------------|
| `upstream-beta`  | `upstream/beta`     | Mirror of upstream dev (default) |
| `upstream-main`  | `upstream/main`     | Mirror of upstream stable        |

These are pure mirrors. Run `scripts/sync-upstream.sh` to update them.

### Our branches

| Branch                        | Based on        | Purpose                                    | Status |
|-------------------------------|-----------------|---------------------------------------------|--------|
| `main`                        | `upstream-beta` | Our integration branch. All features merge here. | Active |
| `feature/openclaw-vnext-plan` | `main`          | Planning + docs branch                      | Active |
| `feat/phase1-snapshot-ref`    | `main`          | Phase 1A: snapshot capture, ref graph, ref resolve | ⚠️ Needs hardening (H-1, H-3, H-4) |
| `feat/phase1-wait-primitives` | `main`          | Phase 1B: wait_for_editor_state, wait_for_gameobject, wait_for_console | ⚠️ Needs hardening (H-2) |

### Flow

```
upstream/beta ──sync──▶ upstream-beta ──rebase──▶ main ──rebase──▶ feature/*
                                                    ◀──PR merge──
```

### Rules

1. **Never commit to `upstream-beta` or `upstream-main`.** They are read-only mirrors.
2. **`main` is our stable integration branch.** All feature PRs target `main`.
3. **Feature branches rebase onto `main`** before PR merge (linear history).
4. **Upstream syncs rebase `main` onto `upstream-beta`** (see §4 for rationale).

---

## 3. Conflict Containment

The #1 rule: **be additive, not invasive.** Minimize edits to upstream files.

### 🔴 Upstream-owned (DO NOT modify unless absolutely necessary)

These directories/files are actively maintained by Coplay. Touching them guarantees merge conflicts on every sync.

```
MCPForUnity/Editor/Tools/        # existing tool files
MCPForUnity/Editor/Services/     # existing service files
MCPForUnity/Editor/Windows/      # existing UI files
Server/src/services/tools/*.py   # existing tool modules
Server/src/transport/*.py        # existing transport files
Server/src/core/config.py        # their config
.github/                         # their CI
tools/update_fork.*              # their fork scripts
docker-compose.yml               # their docker setup
manifest.json                    # their package manifest
README.md                        # their readme
```

**If you must patch an upstream file:**
- Isolate changes in clearly marked blocks:
  ```python
  # --- BEGIN OPENCLAW EXTENSION ---
  ...
  # --- END OPENCLAW EXTENSION ---
  ```
- Add the file path to `docs/development/UPSTREAM_PATCHES.md` with rationale.
- Keep patches minimal — prefer hooking/wrapping over inline edits.

### 🟢 Our extension zones (safe to create/modify freely)

```
Server/src/services/tools/openclaw/    # our new tool modules (namespaced)
Server/src/services/tools/wait_for.py  # new file (no upstream collision) — implemented
Server/src/services/tools/scene_snapshot.py  # new file — implemented
Server/src/services/tools/ref_resolve.py     # new file — implemented
Server/src/services/snapshot/          # new package (ref graph, snapshot store) — implemented
Server/src/services/tools/qa_scenario.py
Server/src/core/trace.py               # new file
Server/tests/integration/test_wait_for_tools.py    # new — implemented
Server/tests/integration/test_scene_snapshot_tools.py  # new — implemented
Server/tests/test_ref_graph.py         # new — implemented
MCPForUnity/Editor/Tools/SceneSnapshotCapture.cs  # new file — PENDING (H-1)
MCPForUnity/Runtime/OpenClaw/          # our runtime bridge (new subdir)
docs/development/                      # our planning/ADR docs
scripts/                               # our scripts (new files only)
tests/openclaw/                        # our test modules
```

### 🟡 Shared zones (coordinate carefully)

These may need minor edits but upstream also touches them:

```
Server/src/main.py                  # tool registration (append only)
Server/src/models/                  # add new models, don't edit existing
MCPForUnity/Editor/Helpers/         # may need serialization extensions
MCPForUnity/Editor/Tools/GameObjects/ManageGameObject.cs  # needs get_info action (H-2b)
MCPForUnity/Runtime/                # upstream has minimal content here
```

**Strategy for shared zones:** Prefer new files. If you must edit an existing file, keep the diff under 10 lines and use the `OPENCLAW EXTENSION` markers.

**Known planned patches to upstream files:**
- `ManageGameObject.cs`: Add `get_info` action case (H-2b) — ~15 lines, use OPENCLAW EXTENSION markers

---

## 4. Rebase vs Merge — Recommendation

**Use rebase for upstream syncs.** Rationale:

1. Our strategy is explicitly additive (new files/modules). Rebase conflicts will be rare.
2. Rebase produces clean linear history — easy to see "our commits on top of upstream."
3. Merge commits create noise and make `git log` harder to read for a small team.
4. Upstream's own `tools/update_fork.sh` already uses rebase — staying consistent.

**Escape hatch:** If a rebase produces >3 conflicts, abort and use merge instead:

```bash
git rebase --abort
git merge upstream/beta --no-ff -m "upstream sync: merge beta $(date +%Y-%m-%d)"
```

**For feature branches → main:** Also rebase (squash or interactive), then fast-forward merge or GitHub squash-merge via PR.

---

## 5. Sync Procedure

### Quick sync (recommended: weekly or before starting new work)

```bash
./scripts/sync-upstream.sh
```

See the script for details. It:
1. Fetches upstream
2. Updates the selected mirror branch (`upstream-beta` by default, `upstream-main` with `--stable`)
3. Rebases `main` onto that mirror branch
4. Pushes updated `main` to origin
5. Reports if conflicts occurred

### Manual sync

```bash
git fetch upstream
git checkout upstream-beta && git reset --hard upstream/beta
git checkout main && git rebase upstream-beta
# resolve conflicts if any
git push origin main
```

### After sync: rebase active feature branches

```bash
git checkout feature/my-branch
git rebase main
# resolve if needed
git push origin feature/my-branch --force-with-lease
```

---

## 6. Handling Breaking Upstream Changes

If upstream restructures directories we extend:

1. **Don't panic.** Our code is in separate files/subdirs — usually unaffected.
2. Check `git diff upstream-beta@{1}..upstream-beta -- Server/src MCPForUnity` for scope.
3. If our patches (§3 markers) conflict, resolve inline — keep markers intact.
4. If an upstream refactor moves a file we hook into, update our import/reference in one commit.
5. Document the incident in `docs/development/UPSTREAM_PATCHES.md`.

---

## 7. CI Considerations (future)

When we add CI workflows:
- Place in `.github/workflows/openclaw-*.yml` (namespaced to avoid collisions).
- Never edit upstream's existing workflow files.
- Test matrix: upstream's supported Unity versions (2021 LTS, 2022 LTS, Unity 6).
