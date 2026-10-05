#!/usr/bin/env bash
# Start a new competition folder from template/.
# Usage: ./new_competition.sh <destination-folder>
#   e.g. ./new_competition.sh ~/competitions/playground-s6e10
# Copies the template, starts a git repository there, and makes the first commit.
# Refuses to write into a folder that already exists.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <destination-folder>" >&2
  exit 2
fi

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
destination="$1"

if [[ -e "$destination" ]]; then
  echo "refused: $destination already exists" >&2
  exit 4
fi

cp -R "$repository_root/template" "$destination"
cd "$destination"
git init -q
git add -A
git commit -q -m "chore: start competition from claude-research-template"

if [[ ! -L "$HOME/.claude/skills/frame-competition" ]]; then
  echo "note: skills are not installed yet — run $repository_root/install.sh once"
fi
echo "Created $destination"
echo "Next: cd $destination && claude, then ask it to frame the competition (skill: frame-competition)."
