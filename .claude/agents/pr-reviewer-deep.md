---
name: pr-reviewer-deep
description: The code reviewer at xhigh effort. Use only when the user asks for it. Pass only the PR number, the plan task and, for a delta review, the previous reviewed head and that report's findings verbatim; never a summary of the work.
tools: Read, Grep, Glob, Bash, WebFetch
disallowedTools: Edit, Write, NotebookEdit
maxTurns: 25
model: opus
effort: xhigh
isolation: worktree
color: orange
# The review procedure lives in the pr-review skill, shared by every reviewer tier.
skills:
  - pr-review
# Blocks git push/commit and GitHub writes while this agent runs (not in the main session).
# `|| exit 2` fails closed: if the script is missing or crashes, the command is blocked.
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: 'python3 "${CLAUDE_PROJECT_DIR}/.claude/hooks/pr_reviewer_guard.py" || exit 2'
---

Review the pull request named in the delegation message by following the preloaded pr-review
skill exactly, and return only the report it defines.
