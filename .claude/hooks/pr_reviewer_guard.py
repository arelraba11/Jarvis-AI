"""PreToolUse hook for the pr-reviewer subagent: block commands that write to git or GitHub.

Reads the hook input JSON on stdin and exits 2 (block, reason on stderr) when the Bash command
would run git push/commit or a GitHub write through gh. Exit 0 lets the normal permission flow
apply. Wired in .claude/agents/pr-reviewer.md, so it runs only while the reviewer is active.

The whole command string is scanned, including quoted parts, so `sh -c "git push"` and
`bash -c 'gh pr merge 1'` are caught. It is a guard against mistakes and injected
instructions in PR text, not a sandbox: an encoded command (base64 piped to sh) gets through.
Mentions count too: `grep "git push" docs` is blocked; search for `git.push` instead.
"""

import json
import re
import sys

# Shell quoting and operators become token breaks, so nested commands are scanned as words.
_SEPARATORS = re.compile(r"""[\s'"`;&|()<>{}$\\]+""")

# git global options that take the next token as their value.
_GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
_GIT_BLOCKED = {"push", "commit"}

_GH_OPTS_WITH_VALUE = {"-R", "--repo"}
_GH_BLOCKED = {
    "pr": {"merge", "comment", "review", "edit", "close", "reopen", "ready", "create"},
    "issue": {"comment", "create", "edit", "close", "reopen"},
    "alias": {"set", "import"},
}
_GH_API_FIELD_FLAGS = ("-f", "-F", "--field", "--raw-field", "--input")


def _is(token: str, name: str) -> bool:
    return token == name or token.endswith("/" + name)


def _git_reason(args: list[str]) -> str | None:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] in _GIT_OPTS_WITH_VALUE:
            if args[i] == "-c" and i + 1 < len(args) and args[i + 1].startswith("alias."):
                return "git -c alias.* (an alias can hide push or commit)"
            i += 1
        i += 1
    if i < len(args) and args[i] in _GIT_BLOCKED:
        return f"git {args[i]}"
    return None


def _gh_positionals(args: list[str]) -> tuple[list[str], list[str]]:
    """Return (first two positional words, all args after the command name)."""
    words: list[str] = []
    i = 0
    while i < len(args) and len(words) < 2:
        if args[i] in _GH_OPTS_WITH_VALUE:
            i += 2
            continue
        if not args[i].startswith("-"):
            words.append(args[i])
        i += 1
    return words, args


def _gh_api_reason(args: list[str]) -> str | None:
    method = None
    has_fields = False
    positionals = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-X", "--method"):
            method = args[i + 1].upper() if i + 1 < len(args) else ""
            i += 2
            continue
        if a.startswith("--method="):
            method = a.split("=", 1)[1].upper()
        elif a.startswith("-X") and len(a) > 2:
            method = a[2:].upper()
        elif a.startswith(_GH_API_FIELD_FLAGS):
            has_fields = True
        elif not a.startswith("-"):
            positionals.append(a)
        i += 1
    if positionals[:1] == ["graphql"]:
        return "gh api graphql (can run mutations; use gh pr view --json to read)"
    if method is not None and method != "GET":
        return f"gh api with method {method}"
    if has_fields and method is None:
        return "gh api with fields and no -X GET (gh sends POST)"
    return None


def _gh_reason(args: list[str]) -> str | None:
    words, _ = _gh_positionals(args)
    if not words:
        return None
    if words[0] == "api":
        return _gh_api_reason(args[args.index("api") + 1 :])
    if len(words) == 2 and words[1] in _GH_BLOCKED.get(words[0], set()):
        return f"gh {words[0]} {words[1]}"
    return None


def blocked_reason(command: str) -> str | None:
    tokens = [t for t in _SEPARATORS.split(command) if t]
    for i, token in enumerate(tokens):
        rest = tokens[i + 1 :]
        reason = None
        if _is(token, "git"):
            reason = _git_reason(rest)
        elif _is(token, "gh"):
            reason = _gh_reason(rest)
        if reason:
            return reason
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
        command = data["tool_input"]["command"] if data.get("tool_name") == "Bash" else ""
        if not isinstance(command, str):
            raise TypeError("tool_input.command is not a string")
    except (ValueError, KeyError, TypeError) as exc:
        # Fail closed: a hook input we cannot read must not let the command through.
        print(f"pr-reviewer guard: cannot read hook input ({exc}); blocked.", file=sys.stderr)
        return 2
    reason = blocked_reason(command)
    if reason:
        print(
            f"pr-reviewer guard: blocked {reason}. The reviewer is read-only: no commits, "
            "pushes, merges, comments or GitHub writes. Report instead of acting.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
