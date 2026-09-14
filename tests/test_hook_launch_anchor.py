"""Hook launch gate — a `.sh` hook command must lead with `bash` and resolve
independently of the session cwd.

Hooks inherit the session working directory, so a cwd-relative path exits 127
the moment the session leaves the repo root — invisibly, because that exit
reaches the user but never Claude.

Accepted: `$CLAUDE_PROJECT_DIR`, `${CLAUDE_PROJECT_DIR}`, absolute paths.
Rejected: `$env:CLAUDE_PROJECT_DIR` — that spelling is for hooks registered
with `shell: "powershell"`, and every hook here runs under bash, where `$env`
expands to nothing and the path dies with exit 127 like any relative one.
"""
import json
from pathlib import Path

import pytest
from meta_schema import _hook_script_token, _is_cwd_independent

ROOT = Path(__file__).resolve().parent.parent

ANCHORED = [
    'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/dispatch.sh" pre',
    'bash "${CLAUDE_PROJECT_DIR}/.claude/hooks/dispatch.sh" pre',
    "bash /c/Users/kookh/repo/.claude/hooks/dispatch.sh pre",
    'bash "C:/Users/kookh/repo/.claude/hooks/lint-chain-guard.sh"',
]

RELATIVE = [
    "bash .claude/hooks/dispatch.sh pre",
    "bash ./.claude/hooks/dispatch.sh post",
    # FN guard: the token appearing anywhere in the command is not enough —
    # the path itself has to be anchored.
    "bash .claude/hooks/dispatch.sh pre # $CLAUDE_PROJECT_DIR",
    # PowerShell-only spelling. bash expands `$env` to empty, leaving
    # `:CLAUDE_PROJECT_DIR/...` — exit 127, the very failure this gate exists
    # to catch. Registered hooks all run under bash (no `shell` key).
    'bash "$env:CLAUDE_PROJECT_DIR/.claude/hooks/dispatch.sh" pre',
]


@pytest.mark.parametrize("cmd", ANCHORED)
def test_cwd_independent_forms_pass(cmd):
    assert _is_cwd_independent(_hook_script_token(cmd)), cmd


@pytest.mark.parametrize("cmd", RELATIVE)
def test_cwd_relative_forms_fail(cmd):
    assert not _is_cwd_independent(_hook_script_token(cmd)), cmd


def test_registered_hooks_are_anchored():
    """The live settings.json must satisfy the gate."""
    data = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for groups in data.get("hooks", {}).values()
        for group in groups
        for hook in group.get("hooks", [])
        if hook.get("type") == "command" and ".sh" in (hook.get("command") or "")
    ]
    assert commands, "no .sh hook commands registered"
    for cmd in commands:
        assert cmd.split()[0] == "bash", cmd
        assert _is_cwd_independent(_hook_script_token(cmd)), cmd
