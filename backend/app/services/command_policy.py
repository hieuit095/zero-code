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

import re
from dataclasses import dataclass
from typing import Any


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
    re.compile(r"\bsu\s+-", re.IGNORECASE),
    re.compile(r"\bchmod\s+777\b", re.IGNORECASE),

    # Crypto miners / downloaders
    re.compile(r"\bwget\s+.*?\|\s*(ba)?sh", re.IGNORECASE),                # wget | sh
    re.compile(r"\bcurl\s+.*?\|\s*(ba)?sh", re.IGNORECASE),                # curl | sh

    # Environment exfiltration
    re.compile(r"\benv\b|\bprintenv\b", re.IGNORECASE),
    re.compile(r"\bcat\s+.*?\.env\b", re.IGNORECASE),
    re.compile(r"\bcat\s+/etc/(passwd|shadow)", re.IGNORECASE),

    # Process/system manipulation
    re.compile(r"\bkill\s+-9\s+1\b", re.IGNORECASE),                       # kill init
    re.compile(r"\bshutdown\b|\breboot\b", re.IGNORECASE),
]


# ─── QA Role Allowlist (QA can ONLY run these patterns) ──────────────────────

_QA_ALLOWLIST: list[re.Pattern] = [
    # Python
    re.compile(r"^python\s+(-m\s+)?(py_compile|pytest|unittest|mypy|ruff|flake8|black\s+--check|pylint)"),
    re.compile(r"^python\s+-c\s+"),                                          # python -c "..."

    # Node.js / TypeScript
    re.compile(r"^(npx|npm\s+run|yarn|pnpm)\s+(test|lint|typecheck|tsc|eslint|prettier\s+--check|vitest|jest)"),
    re.compile(r"^npx\s+tsc\b"),
    re.compile(r"^node\s+--check\b"),

    # Shell read-only
    re.compile(r"^(ls|dir|cat|head|tail|wc|find|tree|file|stat|type)\b"),
    re.compile(r"^(grep|rg|ag|fd)\b"),
    re.compile(r"^echo\b"),

    # Go
    re.compile(r"^go\s+(vet|test|build)\b"),

    # Rust
    re.compile(r"^cargo\s+(check|test|clippy)\b"),
]


# ─── Dev Role Blocklist (Dev-specific restrictions on top of global) ─────────

_DEV_EXTRA_BLOCKLIST: list[re.Pattern] = [
    # Prevent installing system-level packages
    re.compile(r"\bapt(-get)?\s+install\b", re.IGNORECASE),
    re.compile(r"\byum\s+install\b", re.IGNORECASE),
    re.compile(r"\bbrew\s+install\b", re.IGNORECASE),

    # Prevent SSH / network
    re.compile(r"\bssh\b", re.IGNORECASE),
    re.compile(r"\bscp\b", re.IGNORECASE),
    re.compile(r"\brsync\b", re.IGNORECASE),
]


# ─── Policy Result ────────────────────────────────────────────────────────────


@dataclass
class PolicyResult:
    """Result of a command safety check."""

    allowed: bool
    command: str
    reason: str = ""
    matched_rule: str = ""

    def to_exec_error(self) -> dict[str, Any]:
        """
        Return a structured error matching the standard exec tool output format.
        This ensures agents can reason about the rejection (Rule 3).
        """
        return {
            "exitCode": 1,
            "stdout": "",
            "stderr": (
                f"⛔ SECURITY POLICY VIOLATION\n"
                f"Command: {self.command}\n"
                f"Reason: {self.reason}\n"
                f"Matched Rule: {self.matched_rule}\n"
                f"This command is not permitted in the sandbox."
            ),
            "durationMs": 0,
        }


# ─── Policy Enforcer ─────────────────────────────────────────────────────────


class CommandPolicy:
    """Enforces command safety policies based on agent role."""

    @staticmethod
    def check(command: str, agent_role: str = "dev") -> PolicyResult:
        """
        Check if a command is allowed for the given agent role.

        Args:
            command: The shell command to validate
            agent_role: "dev" or "qa"

        Returns:
            PolicyResult with allowed=True/False and reason.
        """
        cmd_stripped = command.strip()

        # 1. Global blocklist (always blocked)
        for pattern in _GLOBAL_BLOCKLIST:
            if pattern.search(cmd_stripped):
                return PolicyResult(
                    allowed=False,
                    command=cmd_stripped,
                    reason="Command matches global security blocklist",
                    matched_rule=pattern.pattern,
                )

        # 2. QA role: allowlist-only
        if agent_role == "qa":
            for pattern in _QA_ALLOWLIST:
                if pattern.search(cmd_stripped):
                    return PolicyResult(allowed=True, command=cmd_stripped)

            return PolicyResult(
                allowed=False,
                command=cmd_stripped,
                reason="QA agent can only run read-only and testing commands",
                matched_rule="qa_allowlist",
            )

        # 3. Dev role: check extra blocklist
        if agent_role == "dev":
            for pattern in _DEV_EXTRA_BLOCKLIST:
                if pattern.search(cmd_stripped):
                    return PolicyResult(
                        allowed=False,
                        command=cmd_stripped,
                        reason="Command blocked for Dev agent",
                        matched_rule=pattern.pattern,
                    )

        # 4. Default: allowed for dev
        return PolicyResult(allowed=True, command=cmd_stripped)
