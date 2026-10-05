#!/usr/bin/env bash
# Install this repo's skills and agents at user level so every competition folder can use them.
#   skills  -> symlinked into ~/.claude/skills/<name>   (edit here once, every competition sees it)
#   agents  -> copied into   ~/.claude/agents/<name>.md (symlinked agents are not documented as supported;
#              re-run this script after editing an agent)
# Never overwrites a skill or agent it did not install: those are skipped with a warning.
#
# Usage: ./install.sh            install / update
#        ./install.sh --uninstall remove only what this script installed
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
skills_target="$HOME/.claude/skills"
agents_target="$HOME/.claude/agents"
installed_agents_record="$agents_target/.claude-research-template-installed"

mkdir -p "$skills_target" "$agents_target"
touch "$installed_agents_record"

if [[ "${1:-}" == "--uninstall" ]]; then
  for skill_directory in "$repository_root"/skills/*/; do
    skill_name="$(basename "$skill_directory")"
    link_path="$skills_target/$skill_name"
    if [[ -L "$link_path" && "$(readlink "$link_path")" == "${skill_directory%/}" ]]; then
      rm "$link_path" && echo "removed skill  $skill_name"
    fi
  done
  while read -r agent_file_name; do
    [[ -n "$agent_file_name" && -f "$agents_target/$agent_file_name" ]] \
      && rm "$agents_target/$agent_file_name" && echo "removed agent  $agent_file_name"
  done < "$installed_agents_record"
  rm -f "$installed_agents_record"
  exit 0
fi

for skill_directory in "$repository_root"/skills/*/; do
  skill_directory="${skill_directory%/}"
  skill_name="$(basename "$skill_directory")"
  link_path="$skills_target/$skill_name"
  if [[ -L "$link_path" && "$(readlink "$link_path")" == "$skill_directory" ]]; then
    echo "ok     skill  $skill_name"
  elif [[ -e "$link_path" || -L "$link_path" ]]; then
    echo "SKIP   skill  $skill_name — $link_path already exists and is not ours" >&2
  else
    ln -s "$skill_directory" "$link_path" && echo "linked skill  $skill_name"
  fi
done

for agent_path in "$repository_root"/agents/*.md; do
  agent_file_name="$(basename "$agent_path")"
  destination="$agents_target/$agent_file_name"
  if [[ -e "$destination" ]] && ! grep -qxF "$agent_file_name" "$installed_agents_record"; then
    echo "SKIP   agent  $agent_file_name — $destination already exists and is not ours" >&2
    continue
  fi
  cp "$agent_path" "$destination"
  grep -qxF "$agent_file_name" "$installed_agents_record" || echo "$agent_file_name" >> "$installed_agents_record"
  echo "copied agent  $agent_file_name"
done

echo "Done. Restart Claude Code so new skills and agents register."
