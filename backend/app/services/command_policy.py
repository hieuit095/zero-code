"""
Command safety policy enforcer for sandbox execution.

Implements:
  - Global blocklist: always-rejected destructive commands
  - Role-based restrictions: QA gets read-only/test-only, Dev gets broader access
  - Structured rejection: returns tool-format error so agents can reason about it

Policy levels:
  - "dev": Can read, write, compile, run tests, use package managers
  - "qa": Can only read files, run linters/tests/type-checkers
"""

from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)


# ─── Global Blocklist (always rejected, any role) ─────────────────────────────

_GLOBAL_BLOCKLIST: list[re.Pattern] = [
    # Destructive filesystem operations
    re.compile(r"\brm\s+(-\w*r\w*f|--recursive).*?/\s*$", re.IGNORECASE),  # rm -rf /
    re.compile(r"\brm\s+(-\w*r\w*f|--recursive)\s+/", re.IGNORECASE),      # rm -rf /...
    re.compile(r"\bmkfs\b", re.IGNORECASE),                                  # format disk
    re.compile(r"\bformat\s+[cCdDeE]:", re.IGNORECASE),                     # Windows format
    re.compile(r"\bdd\s+.*?\bof=/dev/", re.IGNORECASE),                     # dd to device
    re.compile(r">\s*/dev/sd[a-z]", re.IGNORECASE),                         # redirect to device

    # Network reconnaissance / attack tools
    re.compile(r"\bnmap\b", re.IGNORECASE),
    re.compile(r"\bnetcat\b|\bnc\s+-", re.IGNORECASE),
    re.compile(r"\bcurl\s+.*?-X\s+(DELETE|PUT|PATCH)", re.IGNORECASE),      # destructive HTTP

    # Privilege escalation
    re.compile(r"\bsudo\s+", re.IGNORECASE),
]


@dataclass
class PolicyResult:
    allowed: bool
    reason: str
    matched_rule: str | None = None

    def to_exec_error(self) -> dict:
        """Format rejection as an agent-readable error response."""
        return {
            "exit_code": 126,
            "stdout": "",
            "stderr": f"POLICY BLOCKED: {self.reason} [rule: {self.matched_rule}]",
            "duration_ms": 0,
            "via": "policy_block",
        }


# ─── Globally Blocked Base Commands ──────────────────────────────────────────
# These commands are NEVER allowed for any agent role.

_GLOBAL_BLOCKED_COMMANDS: set[str] = {
    # Network reconnaissance / exploitation
    "nmap", "nc", "ncat", "netcat", "telnet", "tcpdump", "wireshark",
    "masscan", "zmap", "sqlmap", "nikto", "dirb", "gobuster",
    # Privilege escalation
    "sudo", "su", "doas", "pkexec",
    # System destruction
    "mkfs", "mkfs.ext4", "mkfs.xfs", "mkfs.btrfs", "mkfs.vfat",
    "fdisk", "parted", "wipefs", "shred",
    # Dangerous system utilities
    "reboot", "shutdown", "halt", "poweroff", "init",
    # Cryptomining / persistence
    "crontab", "at", "systemctl", "service",
    # Container escapes
    "docker", "podman", "nsenter", "unshare", "chroot",
    # Remote access
    "ssh", "scp", "rsync", "sftp", "ftp", "wget", "curl",
}

# ─── Destructive Command Detection ──────────────────────────────────────────

_DESTRUCTIVE_RM_FLAGS = {"-rf", "-fr", "-r", "--recursive"}
_DANGEROUS_RM_TARGETS = {"/", ".", "..", "*", "~", "/*", "../*", "../../*"}


def _is_destructive_rm(tokens: list[str]) -> str | None:
    """
    Detect dangerous `rm` invocations by analyzing flags and targets.
    Returns a reason string if destructive, None if safe.
    """
    if not tokens or tokens[0] != "rm":
        return None

    flags: set[str] = set()
    targets: list[str] = []

    for token in tokens[1:]:
        if token.startswith("-"):
            # Normalize combined flags: -rf -> -r, -f
            if not token.startswith("--"):
                for char in token[1:]:
                    flags.add(f"-{char}")
            flags.add(token)
        else:
            targets.append(token)

    is_recursive = bool(flags & {"-r", "-R", "--recursive"})
    is_forced = "-f" in flags or "--force" in flags

    # rm -rf with any dangerous target
    if is_recursive and is_forced:
        for target in targets:
            if target in _DANGEROUS_RM_TARGETS or target.startswith("/"):
                return f"rm with recursive+force on dangerous target '{target}'"
        # Even without a specific dangerous target, rm -rf is risky
        if not targets:
            return "rm with recursive+force and no target specified"

    # rm -r on root-level paths
    if is_recursive:
        for target in targets:
            if target in {"/", ".", "~", "/*"}:
                return f"rm recursive on dangerous target '{target}'"

    return None


def _is_destructive_dd(tokens: list[str]) -> str | None:
    """Detect dangerous dd commands that overwrite disks."""
    if not tokens or tokens[0] != "dd":
        return None

    for token in tokens[1:]:
        if token.startswith("of="):
            target = token[3:]
            if target.startswith("/dev/") or target in {"/", "."}:
                return f"dd writing to dangerous target '{target}'"

    return "dd command blocked (potential disk destruction)"


# ─── QA Allowlist ────────────────────────────────────────────────────────────
# QA agent can ONLY run these base commands (verification-only).

_QA_ALLOWED_COMMANDS: set[str] = {
    # Testing
    "pytest", "python", "python3", "node", "npx", "npm", "yarn", "pnpm",
    "jest", "vitest", "mocha",
    # Linting / formatting
    "ruff", "black", "isort", "flake8", "mypy", "pyright", "pylint",
    "eslint", "prettier", "tsc",
    # Build verification
    "make", "cargo",
    # Read-only inspection
    "cat", "head", "tail", "less", "wc", "grep", "find", "ls", "tree",
    "diff", "echo", "env", "printenv", "which", "whoami", "pwd",
}

# ─── Dev Extra Blocklist ─────────────────────────────────────────────────────
# Additional commands blocked specifically for the Dev agent.

_DEV_EXTRA_BLOCKED: set[str] = {
    "apt", "apt-get", "yum", "dnf", "brew", "pacman", "pip", "pip3",
    "gem", "cargo", "go",
}


# ─── Quote-Aware Shell Segment Splitter ──────────────────────────────────────
# AUDIT FIX: Replaces naive str.split() which broke commands containing
# |, &&, ||, ; inside quoted strings (e.g., echo "foo && bar").


def _split_shell_segments(command: str) -> list[str]:
    """
    Split a command string on shell operators (|, &&, ||, ;) while
    respecting single and double quotes.

    Characters inside matching quotes are never treated as operators.
    Returns a list of command segments. If no operators are found
    outside quotes, the entire command is returned as a single segment.
    """
    segments: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(command)

    while i < n:
        ch = command[i]

        # ── Track quote state ─────────────────────────────────
        if ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
            i += 1
            continue

        # ── Only split on operators when OUTSIDE quotes ───────
        if not in_single and not in_double:
            # Check two-char operators first: &&, ||
            two = command[i: i + 2]
            if two in ("&&", "||"):
                segments.append("".join(current))
                current = []
                i += 2
                continue
            # Single-char operators: |, ;
            if ch in ("|", ";"):
                segments.append("".join(current))
                current = []
                i += 1
                continue

        current.append(ch)
        i += 1

    # Flush remaining
    segments.append("".join(current))
    return segments


class CommandPolicy:
    """Production-grade command policy using shlex parsing."""

    @staticmethod
    def check(
        command: str,
        role: Literal["dev", "qa", "tech-lead"] = "dev",
    ) -> PolicyResult:
        """
        Evaluate a command string against the security policy.

        Uses shlex.split() for robust tokenization that handles quoting,
        escaping, and multi-word arguments correctly.
        """
        # ── Step 1: Split on shell operators (|, &&, ||, ;) ────────
        # AUDIT FIX: Use a quote-aware splitter so operators inside
        # single or double quotes are treated as literal text, not
        # as command separators.
        segments = _split_shell_segments(command)

        if len(segments) > 1:
            for seg in segments:
                seg = seg.strip()
                if not seg:
                    continue
                result = CommandPolicy.check(seg, role)
                if not result.allowed:
                    return PolicyResult(
                        allowed=False,
                        reason=f"Chained/piped command contains blocked segment: {result.reason}",
                        matched_rule=result.matched_rule,
                    )

        # ── Step 3: Tokenize with shlex ──────────────────────────
        try:
            tokens = shlex.split(command)
        except ValueError:
            return PolicyResult(
                allowed=False,
                reason="Command could not be parsed safely (unmatched quote or escape)",
                matched_rule="shlex_parse_error",
            )

        if not tokens:
            return PolicyResult(allowed=True, reason="Empty command")

        base_command = tokens[0].split("/")[-1]  # handle /usr/bin/rm -> rm

        # ── Step 4: Global blocklist ─────────────────────────────
        if base_command in _GLOBAL_BLOCKED_COMMANDS:
            return PolicyResult(
                allowed=False,
                reason=f"Command '{base_command}' is globally blocked",
                matched_rule="global_blocklist",
            )

        # ── Step 5: Destructive command detection ────────────────
        rm_issue = _is_destructive_rm(tokens)
        if rm_issue:
            return PolicyResult(
                allowed=False,
                reason=rm_issue,
                matched_rule="destructive_rm",
            )

        dd_issue = _is_destructive_dd(tokens)
        if dd_issue:
            return PolicyResult(
                allowed=False,
                reason=dd_issue,
                matched_rule="destructive_dd",
            )

        # ── Step 6: Role-based enforcement ───────────────────────
        if role == "qa":
            if base_command not in _QA_ALLOWED_COMMANDS:
                return PolicyResult(
                    allowed=False,
                    reason=f"QA agent is not allowed to run '{base_command}' (allowlist-only)",
                    matched_rule="qa_allowlist",
                )

        if role == "dev":
            if base_command in _DEV_EXTRA_BLOCKED:
                return PolicyResult(
                    allowed=False,
                    reason=f"Dev agent is not allowed to run '{base_command}'",
                    matched_rule="dev_blocklist",
                )

        return PolicyResult(allowed=True, reason="Allowed by policy")
