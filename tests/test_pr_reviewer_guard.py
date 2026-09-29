"""The pr-reviewer's PreToolUse hook: blocks git/GitHub writes, lets reads through.

Runs the script as Claude Code does: hook input JSON on stdin, exit 2 blocks.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / ".claude" / "hooks" / "pr_reviewer_guard.py"
AGENT = ROOT / ".claude" / "agents" / "pr-reviewer.md"


def run_guard(stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD)], input=stdin, capture_output=True, text=True, check=False
    )


def bash(command: str) -> str:
    return json.dumps(
        {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}
    )


@pytest.mark.parametrize(
    "command",
    [
        "git push",
        "git push origin HEAD:main --force",
        "git commit -m x",
        "git -C /repo push",
        "git -c user.name=x commit -am y",
        "git --git-dir .git push",
        "/usr/bin/git push",
        "git -c alias.p=push p",
        "cd /repo && git push",
        "true; git commit -m x",
        'sh -c "git push"',
        "bash -c 'gh pr merge 17 --squash'",
        "$(git push)",
        "gh pr merge 17",
        "gh pr --repo o/r merge 17",
        "gh pr comment 17 -b hi",
        "gh pr review 17 --approve",
        "gh pr edit 17 --title x",
        "gh pr close 17",
        "gh issue comment 3 -b hi",
        "gh alias set m 'pr merge'",
        "gh api -X POST repos/o/r/issues/17/comments -f body=hi",
        "gh api --method=PATCH repos/o/r/pulls/17",
        "gh api -XDELETE repos/o/r/git/refs/heads/x",
        "gh api repos/o/r/pulls/17/reviews -f event=APPROVE",
        "gh api repos/o/r/pulls/17/merge --input body.json",
        "gh api graphql -f query='mutation { x }'",
    ],
)
def test_blocks_writes(command: str) -> None:
    result = run_guard(bash(command))
    assert result.returncode == 2
    assert "pr-reviewer guard: blocked" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "gh pr checkout 17 --detach",
        "gh pr view 17 --json headRefOid -q .headRefOid",
        "gh pr diff 17",
        "gh pr checks 17",
        "gh api repos/o/r/pulls/17",
        "gh api -X GET repos/o/r/pulls/17/comments -f per_page=100",
        "git rev-parse HEAD",
        "git log --grep commit --oneline",
        "git diff c1a643b HEAD",
        "git show HEAD:CLAUDE.md",
        "uv run pytest -q && uv run mypy",
        "grep -rn pushd docs",
    ],
)
def test_allows_reads(command: str) -> None:
    result = run_guard(bash(command))
    assert result.returncode == 0, result.stderr


def test_ignores_other_tools() -> None:
    stdin = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/repo/x"}})
    assert run_guard(stdin).returncode == 0


@pytest.mark.parametrize("stdin", ["", "not json", '{"tool_name": "Bash"}', bash("x")[:-5]])
def test_unreadable_input_fails_closed(stdin: str) -> None:
    result = run_guard(stdin)
    assert result.returncode == 2
    assert "cannot read hook input" in result.stderr


def test_agent_frontmatter_wires_the_guard() -> None:
    frontmatter = AGENT.read_text().split("---")[1]
    config = yaml.safe_load(frontmatter)
    (entry,) = config["hooks"]["PreToolUse"]
    (hook,) = entry["hooks"]
    assert entry["matcher"] == "Bash"
    assert hook["type"] == "command"
    assert "/.claude/hooks/pr_reviewer_guard.py" in hook["command"]
    # Fail closed when python3 or the script is missing.
    assert hook["command"].endswith("|| exit 2")
