#!/usr/bin/env bash
#
# Install (or uninstall) the coaching-interpretation skill for Claude Code.
#
# By default this symlinks the skill into your personal skills directory, so edits in this
# repo stay live, and scaffolds a private config file you fill in once. Pass --copy for a
# standalone copy instead, or --uninstall to remove the skill.
#
#   ./install.sh             # symlink the skill + scaffold ~/.config/threshold/config.toml
#   ./install.sh --copy      # copy the skill folder instead of symlinking
#   ./install.sh --uninstall # remove the installed skill (config and vault left untouched)
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_SRC="$REPO_DIR/skills/coaching-interpretation"
SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
DEST="$SKILLS_DIR/coaching-interpretation"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/threshold"
CONFIG="$CONFIG_DIR/config.toml"

if [ "${1:-}" = "--uninstall" ]; then
  rm -rf "$DEST"
  echo "Removed $DEST"
  echo "(Left untouched: your config at $CONFIG and your vault.)"
  exit 0
fi

if [ ! -f "$SKILL_SRC/SKILL.md" ]; then
  echo "error: can't find the skill at $SKILL_SRC" >&2
  exit 1
fi

# 1. Install the skill.
mkdir -p "$SKILLS_DIR"
rm -rf "$DEST"
if [ "${1:-}" = "--copy" ]; then
  cp -R "$SKILL_SRC" "$DEST"
  echo "Copied skill to $DEST"
else
  ln -s "$SKILL_SRC" "$DEST"
  echo "Linked $DEST -> $SKILL_SRC"
fi

# 2. Scaffold a private config file (never overwrite an existing one).
if [ -f "$CONFIG" ]; then
  echo "Config already at $CONFIG (left as-is)."
else
  mkdir -p "$CONFIG_DIR"
  cp "$SKILL_SRC/config.example.toml" "$CONFIG"
  chmod 600 "$CONFIG"
  echo "Created $CONFIG (chmod 600)."
fi

cat <<EOF

Skill installed. Two things before you use it:

  1. The 'claude' CLI must be on your PATH (Claude Code provides it).
  2. Edit your config and fill in the real values:

       \$EDITOR $CONFIG
         athlete_id, api_key   (intervals.icu -> Settings -> Developer)
         vault                 (any folder Obsidian opens; can be empty)

Then, in Claude Code, just ask — e.g. "how did my last run go?" — or run it directly:

    python3 $DEST/scripts/coach.py

EOF
