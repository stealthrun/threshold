#!/usr/bin/env bash
#
# Install the coaching-interpretation skill into Claude Code.
#
# By default this symlinks the skill into your personal skills directory, so edits in this
# repo stay live. Pass --copy for a standalone copy instead (e.g. to hand the skill to
# someone else, or to pin it). Re-running is safe: an existing install is replaced.
#
#   ./install.sh           # symlink ~/.claude/skills/coaching-interpretation -> this repo
#   ./install.sh --copy    # copy the skill folder instead of symlinking
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_SRC="$REPO_DIR/skills/coaching-interpretation"
SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
DEST="$SKILLS_DIR/coaching-interpretation"

if [ ! -f "$SKILL_SRC/SKILL.md" ]; then
  echo "error: can't find the skill at $SKILL_SRC" >&2
  exit 1
fi

mkdir -p "$SKILLS_DIR"
rm -rf "$DEST"

if [ "${1:-}" = "--copy" ]; then
  cp -R "$SKILL_SRC" "$DEST"
  echo "Copied skill to $DEST"
else
  ln -s "$SKILL_SRC" "$DEST"
  echo "Linked $DEST -> $SKILL_SRC"
fi

cat <<'EOF'

Skill installed. Two things before you use it:

  1. The `claude` CLI must be on your PATH (Claude Code provides it).
  2. Export your intervals.icu credentials (key is a secret; read from the env only):

       export INTERVALS_ATHLETE_ID=i12345
       export INTERVALS_API_KEY=...        # Settings -> Developer on intervals.icu

Then, in Claude Code, just ask — e.g. "how did my last run go?" — or run it directly:

    python3 ~/.claude/skills/coaching-interpretation/scripts/coach.py --vault ~/ObsidianVault

EOF
