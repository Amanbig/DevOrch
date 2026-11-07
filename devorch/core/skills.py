"""
Skills system for DevOrch — loadable, reusable prompt templates and workflows
that can be invoked via slash commands.

Skills are defined as YAML files under ~/.devorch/skills/:

    # ~/.devorch/skills/commit.yaml
    name: commit
    description: Create a git commit with a descriptive message
    prompt: |
      Look at the current git diff (staged and unstaged changes) and create
      a well-formatted git commit. Follow conventional commit format.
      First stage relevant files, then commit with a descriptive message.

    # ~/.devorch/skills/review.yaml
    name: review
    description: Review code changes for bugs and improvements
    prompt: |
      Review the current git diff for:
      1. Bugs or logic errors
      2. Security issues
      3. Performance problems
      4. Code style issues
      Provide specific, actionable feedback.

Custom slash commands can also be written as Markdown files:

    ~/.devorch/commands/<name>.md          (global)
    <project>/.devorch/commands/<name>.md  (project; overrides global and skills)

    ---
    description: Review a pull request
    ---
    Review PR $ARGUMENTS: summarize the change, then list bugs and risks.

The file name (without .md) is the command name. ``$ARGUMENTS`` in the body is replaced
with whatever the user types after the command (e.g. ``/pr 123``); if the body has no
``$ARGUMENTS`` placeholder, the arguments are appended to the prompt.

Built-in skills are also provided for common workflows.
"""

import os
from pathlib import Path

try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

SKILLS_DIR = Path.home() / ".devorch" / "skills"

COMMANDS_SUBDIR = Path(".devorch") / "commands"


def parse_markdown_command(text: str) -> tuple[dict, str]:
    """Split optional ``---`` YAML frontmatter from a Markdown command body."""
    meta: dict = {}
    body = text
    if text.startswith("---"):
        parts = text.split("\n")
        for i in range(1, len(parts)):
            if parts[i].strip() == "---":
                if YAML_AVAILABLE:
                    try:
                        loaded = yaml.safe_load("\n".join(parts[1:i]))
                        if isinstance(loaded, dict):
                            meta = loaded
                    except Exception:
                        pass
                body = "\n".join(parts[i + 1 :])
                break
    return meta, body.strip()


def render_prompt(skill: dict, args: str | None = None) -> str:
    """Build the final prompt for a skill/command, substituting user arguments."""
    prompt = skill["prompt"]
    args = (args or "").strip()
    if "$ARGUMENTS" in prompt:
        return prompt.replace("$ARGUMENTS", args)
    if args:
        return f"{prompt}\n\n{args}"
    return prompt


# ── Built-in skills ──────────────────────────────────────────────────────────

BUILTIN_SKILLS: dict[str, dict] = {
    "commit": {
        "name": "commit",
        "description": "Create a git commit with a well-formatted message",
        "prompt": (
            "Look at the current git status and diff (both staged and unstaged changes). "
            "Stage the relevant changed files (prefer specific files over 'git add -A'). "
            "Then create a git commit with a clear, descriptive message following conventional "
            "commit format (e.g., 'feat:', 'fix:', 'refactor:', 'docs:', 'chore:'). "
            "Summarize what changed and why. Show me the commit result."
        ),
    },
    "review": {
        "name": "review",
        "description": "Review current code changes for issues",
        "prompt": (
            "Review the current git diff (run 'git diff' and 'git diff --staged') for:\n"
            "1. Bugs or logic errors\n"
            "2. Security vulnerabilities\n"
            "3. Performance issues\n"
            "4. Code style and readability\n"
            "5. Missing error handling\n\n"
            "Provide specific, actionable feedback with file:line references."
        ),
    },
    "test": {
        "name": "test",
        "description": "Run project tests and analyze results",
        "prompt": (
            "Detect the project's test framework and run the tests. "
            "If tests fail, analyze the failures and suggest fixes. "
            "Common test commands to try: pytest, npm test, cargo test, go test ./..., "
            "python -m unittest discover. Check package.json, pyproject.toml, Cargo.toml, "
            "or Makefile for the correct test command."
        ),
    },
    "explain": {
        "name": "explain",
        "description": "Explain the current project structure",
        "prompt": (
            "Analyze the current project directory structure. Identify:\n"
            "1. What type of project this is (language, framework)\n"
            "2. Key entry points and main files\n"
            "3. Directory structure and organization\n"
            "4. Dependencies and build system\n"
            "5. How to run/build/test the project\n\n"
            "Give a concise overview suitable for someone new to the project."
        ),
    },
    "fix": {
        "name": "fix",
        "description": "Fix the last error or failing test",
        "prompt": (
            "Look at the most recent error output (check shell history, test results, "
            "or build logs). Diagnose the root cause and fix it. "
            "After fixing, re-run the command to verify the fix works."
        ),
    },
    "simplify": {
        "name": "simplify",
        "description": "Review and simplify recent code changes",
        "prompt": (
            "Look at the recent code changes (git diff HEAD~1 or staged changes). "
            "Review for:\n"
            "1. Code that can be simplified or made more readable\n"
            "2. Unnecessary complexity or over-engineering\n"
            "3. Duplicated logic that could be consolidated\n"
            "4. Better naming opportunities\n\n"
            "Make the improvements directly."
        ),
    },
}


# ── Skill Manager ────────────────────────────────────────────────────────────


class SkillManager:
    """Manages built-in and user-defined skills."""

    def __init__(
        self,
        skills_dir: Path | None = None,
        commands_dirs: list[Path] | None = None,
    ):
        self.skills_dir = skills_dir or SKILLS_DIR
        # Later directories override earlier ones: global first, then project.
        self.commands_dirs = (
            commands_dirs
            if commands_dirs is not None
            else [Path.home() / COMMANDS_SUBDIR, Path.cwd() / COMMANDS_SUBDIR]
        )
        self._skills: dict[str, dict] = {}
        self._load_skills()

    def _load_skills(self):
        """Load built-in skills and user-defined skills from disk."""
        # Load built-in skills first
        self._skills = dict(BUILTIN_SKILLS)

        # Load user skills (these override built-ins with the same name)
        if YAML_AVAILABLE and self.skills_dir.exists():
            for filepath in self.skills_dir.glob("*.yaml"):
                try:
                    with open(filepath) as f:
                        skill_data = yaml.safe_load(f)

                    if isinstance(skill_data, dict) and "name" in skill_data:
                        self._skills[skill_data["name"]] = {
                            "name": skill_data["name"],
                            "description": skill_data.get("description", ""),
                            "prompt": skill_data.get("prompt", ""),
                            "source": str(filepath),
                        }
                except Exception:
                    continue

            for filepath in self.skills_dir.glob("*.yml"):
                try:
                    with open(filepath) as f:
                        skill_data = yaml.safe_load(f)

                    if isinstance(skill_data, dict) and "name" in skill_data:
                        self._skills[skill_data["name"]] = {
                            "name": skill_data["name"],
                            "description": skill_data.get("description", ""),
                            "prompt": skill_data.get("prompt", ""),
                            "source": str(filepath),
                        }
                except Exception:
                    continue

        self._load_markdown_commands()

    def _load_markdown_commands(self):
        """Load Markdown slash commands (global, then project)."""
        for directory in self.commands_dirs:
            if not directory.is_dir():
                continue
            for filepath in sorted(directory.glob("*.md")):
                try:
                    meta, body = parse_markdown_command(filepath.read_text(encoding="utf-8"))
                except OSError:
                    continue
                if not body:
                    continue
                name = filepath.stem
                self._skills[name] = {
                    "name": name,
                    "description": str(meta.get("description", "")) or f"Custom command {name}",
                    "prompt": body,
                    "source": str(filepath),
                }

    def get(self, name: str) -> dict | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> list[dict]:
        """List all available skills."""
        result = []
        for _name, skill in sorted(self._skills.items()):
            result.append(
                {
                    "name": skill["name"],
                    "description": skill.get("description", ""),
                    "source": skill.get("source", "built-in"),
                }
            )
        return result

    def create_skill(self, name: str, description: str, prompt: str) -> str:
        """Create a new user skill and save to disk."""
        if not YAML_AVAILABLE:
            return "Error: PyYAML is required to save skills."

        self.skills_dir.mkdir(parents=True, exist_ok=True)

        skill_data = {
            "name": name,
            "description": description,
            "prompt": prompt,
        }

        filepath = self.skills_dir / f"{name}.yaml"
        with open(filepath, "w") as f:
            yaml.safe_dump(skill_data, f, default_flow_style=False)

        self._skills[name] = {
            "name": name,
            "description": description,
            "prompt": prompt,
            "source": str(filepath),
        }

        return str(filepath)

    def delete_skill(self, name: str) -> bool:
        """Delete a user-defined skill."""
        if name in BUILTIN_SKILLS and name not in self._skills:
            return False

        skill = self._skills.get(name)
        if not skill:
            return False

        source = skill.get("source", "")
        if source and source != "built-in" and os.path.exists(source):
            os.unlink(source)

        del self._skills[name]
        return True

    def reload(self):
        """Reload skills from disk."""
        self._load_skills()
