#!/usr/bin/env bash
# sync-upstream.sh — Pull latest from CoplayDev/unity-mcp and rebase our main.
#
# Usage:
#   ./scripts/sync-upstream.sh              # default: sync from upstream/beta
#   ./scripts/sync-upstream.sh --stable     # sync from upstream/main (stable releases only)
#   ./scripts/sync-upstream.sh --dry-run    # fetch + show what would change, don't rebase
#
# Prerequisites:
#   - Remote 'upstream' must point to https://github.com/CoplayDev/unity-mcp.git
#   - Remote 'origin' must point to your fork
#   - Working tree must be clean (stash or commit first)

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

UPSTREAM_BRANCH="beta"   # CoplayDev's active dev branch (their default)
DRY_RUN=false

for arg in "$@"; do
  case $arg in
    --stable)  UPSTREAM_BRANCH="main" ;;
    --dry-run) DRY_RUN=true ;;
    -h|--help)
      echo "Usage: $0 [--stable] [--dry-run]"
      echo "  --stable   Sync from upstream/main instead of upstream/beta"
      echo "  --dry-run  Fetch and report, don't rebase or push"
      exit 0
      ;;
    *) echo "Unknown arg: $arg"; exit 1 ;;
  esac
done

MIRROR_BRANCH="upstream-${UPSTREAM_BRANCH}"
CURRENT_BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo "DETACHED")

# --- Preflight checks ---

if ! git remote get-url upstream &>/dev/null; then
  echo -e "${RED}ERROR: No 'upstream' remote found.${NC}"
  echo "Run: git remote add upstream https://github.com/CoplayDev/unity-mcp.git"
  exit 1
fi

if ! git diff-index --quiet HEAD -- 2>/dev/null; then
  echo -e "${RED}ERROR: Working tree is dirty. Commit or stash first.${NC}"
  exit 1
fi

# --- Fetch upstream ---

echo -e "${GREEN}Fetching upstream...${NC}"
git fetch upstream --prune

UPSTREAM_HEAD=$(git rev-parse upstream/${UPSTREAM_BRANCH})
LOCAL_MAIN=$(git rev-parse main 2>/dev/null || echo "none")

echo -e "  upstream/${UPSTREAM_BRANCH}: ${UPSTREAM_HEAD:0:10}"
echo -e "  local main:                  ${LOCAL_MAIN:0:10}"

if [ "$UPSTREAM_HEAD" = "$LOCAL_MAIN" ]; then
  echo -e "${GREEN}Already up to date.${NC}"
  if [ "$CURRENT_BRANCH" != "main" ] && [ "$CURRENT_BRANCH" != "DETACHED" ]; then
    git checkout "$CURRENT_BRANCH"
  fi
  exit 0
fi

# --- Show what's new ---

NEW_COMMITS=$(git rev-list main..upstream/${UPSTREAM_BRANCH} 2>/dev/null | wc -l | tr -d ' ')
echo -e "${YELLOW}${NEW_COMMITS} new upstream commits since last sync.${NC}"
echo ""
echo "Recent upstream changes:"
git log --oneline main..upstream/${UPSTREAM_BRANCH} 2>/dev/null | head -15
echo ""

if $DRY_RUN; then
  echo -e "${YELLOW}DRY RUN: No changes made.${NC}"
  echo ""
  echo "Files changed upstream:"
  git diff --stat main..upstream/${UPSTREAM_BRANCH} 2>/dev/null | tail -5
  exit 0
fi

# --- Update mirror branch ---

echo -e "${GREEN}Updating mirror branch '${MIRROR_BRANCH}'...${NC}"
if git show-ref --verify --quiet refs/heads/${MIRROR_BRANCH}; then
  git checkout ${MIRROR_BRANCH}
  git reset --hard upstream/${UPSTREAM_BRANCH}
else
  git checkout -b ${MIRROR_BRANCH} upstream/${UPSTREAM_BRANCH}
fi

# --- Rebase main ---

echo -e "${GREEN}Rebasing 'main' onto '${MIRROR_BRANCH}'...${NC}"
git checkout main

if ! git rebase ${MIRROR_BRANCH}; then
  echo ""
  echo -e "${RED}CONFLICT during rebase!${NC}"
  echo ""
  echo "Options:"
  echo "  1. Resolve conflicts, then: git rebase --continue"
  echo "  2. Abort rebase: git rebase --abort"
  echo "  3. Fall back to merge:"
  echo "     git rebase --abort"
  echo "     git merge ${MIRROR_BRANCH} --no-ff -m 'upstream sync: merge ${UPSTREAM_BRANCH} $(date +%Y-%m-%d)'"
  echo ""
  echo -e "${YELLOW}Leaving you on 'main' mid-rebase. Fix and continue.${NC}"
  exit 1
fi

# --- Push ---

echo -e "${GREEN}Pushing updated branches to origin...${NC}"
git push origin ${MIRROR_BRANCH} --force-with-lease
git push origin main --force-with-lease

# --- Return to original branch ---

if [ "$CURRENT_BRANCH" != "main" ] && [ "$CURRENT_BRANCH" != "$MIRROR_BRANCH" ] && [ "$CURRENT_BRANCH" != "DETACHED" ]; then
  git checkout "$CURRENT_BRANCH"
  echo -e "${YELLOW}Tip: Rebase your branch onto main:${NC}"
  echo "  git rebase main"
fi

echo ""
echo -e "${GREEN}✅ Upstream sync complete.${NC}"
echo "  upstream/${UPSTREAM_BRANCH} → ${MIRROR_BRANCH} → main → origin/main"
echo "  ${NEW_COMMITS} commits absorbed."
