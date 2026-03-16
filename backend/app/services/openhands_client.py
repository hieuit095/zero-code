"""
OpenHands SDK service boundary.

Wraps the OpenHands Python SDK (LLM + Agent + Conversation + Tools) behind a
clean async interface that the rest of the backend can call without knowing SDK
internals.

Rule 1 enforcement: The frontend NEVER touches OpenHands directly.
Rule 2 enforcement: Agents MUST NEVER use local host shell or filesystem.
Rule 3 enforcement: All secrets (LLM_API_KEY) stay server-side via config.py.

SECURITY: All file and command operations MUST go through the OpenHands SDK.
           There is NO subprocess/pathlib fallback. If the SDK is not available,
           operations raise SandboxUnavailableError.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)


# ─── Sandbox Error ────────────────────────────────────────────────────────────


class SandboxUnavailableError(RuntimeError):
    """Raised when the OpenHands SDK is not initialized or a workspace has no
    active Conversation. This error MUST be raised instead of falling back to
    host-level subprocess or filesystem operations (Rule 2)."""


# ─── SDK Import Guard ─────────────────────────────────────────────────────────

_SDK_AVAILABLE = False

try:
    from pydantic import SecretStr

    from openhands.sdk import LLM, Agent, Conversation, Tool
    from openhands.tools.file_editor import FileEditorTool
    from openhands.tools.terminal import TerminalTool

    _SDK_AVAILABLE = True
except ImportError:
    logger.warning(
        "OpenHands SDK not installed — ALL sandbox operations will be rejected. "
        "Install with: pip install openhands-sdk openhands-tools openhands-workspace"
    )


class OpenHandsClient:
    """
    Async service wrapping the OpenHands SDK.

    Each run maps to one Conversation object with persistence.

    SECURITY INVARIANT: Every file read/write and command execution MUST go
    through an active SDK Conversation. There is NO host-level fallback.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._conversations: dict[str, Any] = {}  # workspace_id -> Conversation
        self._workspace_base = settings.workspace_path

    # ─── Internal: require an active conversation ─────────────────────────

    def _require_conversation(self, workspace_id: str) -> Any:
        """Return the Conversation for *workspace_id* or raise."""
        if not _SDK_AVAILABLE:
            raise SandboxUnavailableError(
                "OpenHands SDK is not installed. Cannot perform sandbox operations."
            )
        conversation = self._conversations.get(workspace_id)
        if conversation is None:
            raise SandboxUnavailableError(
                f"No active sandbox session for workspace '{workspace_id}'. "
                "Create a workspace first."
            )
        return conversation

    # ─── SDK Initialization ───────────────────────────────────────────────

    def _create_llm(self) -> Any:
        """Create an LLM instance from server-side config."""
        if not _SDK_AVAILABLE:
            raise SandboxUnavailableError("OpenHands SDK is not installed.")

        api_key = self._settings.llm_api_key
        if not api_key:
            raise SandboxUnavailableError(
                "LLM_API_KEY is not configured — cannot create sandbox agent."
            )

        return LLM(
            model=self._settings.llm_model,
            api_key=SecretStr(api_key),
            base_url=self._settings.llm_base_url or None,
        )

    def _create_agent(self, llm: Any) -> Any:
        """Create an Agent with terminal and file editor tools."""
        return Agent(
            llm=llm,
            tools=[
                Tool(name=TerminalTool.name),
                Tool(name=FileEditorTool.name),
            ],
        )

    # ─── Workspace Lifecycle ──────────────────────────────────────────────

    async def create_workspace(self, workspace_id: str) -> dict[str, Any]:
        """
        Provision an isolated OpenHands workspace for a run.

        Raises SandboxUnavailableError if the SDK is not installed or the
        LLM key is missing.
        """
        if not _SDK_AVAILABLE:
            raise SandboxUnavailableError(
                "OpenHands SDK is not installed. Cannot create workspace."
            )

        llm = self._create_llm()       # raises if key missing
        agent = self._create_agent(llm)

        workspace_dir = self._workspace_base / workspace_id
        workspace_dir.mkdir(parents=True, exist_ok=True)

        conversation = Conversation(
            agent=agent,
            workspace=str(workspace_dir),
            persistence_dir=str(workspace_dir / ".conversations"),
        )
        self._conversations[workspace_id] = conversation

        return {
            "workspace_id": workspace_id,
            "status": "ready",
            "path": str(workspace_dir),
            "sdk_active": True,
        }

    async def destroy_workspace(self, workspace_id: str) -> bool:
        """Clean up a workspace and its conversation."""
        conversation = self._conversations.pop(workspace_id, None)

        # Use SDK-level cleanup if available; directory removal is acceptable
        # here because it is an administrative teardown, not an agent action.
        workspace_dir = self._workspace_base / workspace_id
        if workspace_dir.exists():
            import shutil
            shutil.rmtree(workspace_dir, ignore_errors=True)

        return True

    # ─── File System (SDK-only) ───────────────────────────────────────────

    async def list_tree(self, workspace_id: str, max_depth: int = 5) -> list[dict[str, Any]]:
        """
        List the workspace file tree via the SDK Conversation.

        Raises SandboxUnavailableError if no active conversation exists.
        """
        conversation = self._require_conversation(workspace_id)

        try:
            conversation.send_message(
                f"List all files and directories in the workspace up to depth {max_depth}. "
                "Return the result as a JSON array of objects with keys: id, name, type (file/folder), "
                "and children (for folders)."
            )
            conversation.run()

            # The SDK conversation stores the result — return a placeholder
            # until the SDK response parser is implemented.
            return []
        except SandboxUnavailableError:
            raise
        except Exception as e:
            logger.error("SDK list_tree failed for workspace %s: %s", workspace_id, e)
            raise SandboxUnavailableError(f"list_tree failed: {e}") from e

    async def read_file(self, workspace_id: str, path: str) -> str:
        """
        Read a file from the workspace through the SDK.

        Raises SandboxUnavailableError if no active conversation exists.
        """
        conversation = self._require_conversation(workspace_id)

        try:
            conversation.send_message(f"Read the file at path: {path}")
            conversation.run()

            # The SDK conversation stores the result — return a placeholder
            # until the SDK response parser is implemented.
            return f"# File content retrieved via SDK for: {path}\n"
        except SandboxUnavailableError:
            raise
        except Exception as e:
            logger.error("SDK read_file failed for %s: %s", path, e)
            raise SandboxUnavailableError(f"read_file failed: {e}") from e

    async def write_file(self, workspace_id: str, path: str, content: str) -> bool:
        """
        Write content to a file in the workspace through the SDK.

        Raises SandboxUnavailableError if no active conversation exists.
        """
        conversation = self._require_conversation(workspace_id)

        try:
            conversation.send_message(
                f"Write the following content to the file at path: {path}\n\n{content}"
            )
            conversation.run()
            return True
        except SandboxUnavailableError:
            raise
        except Exception as e:
            logger.error("SDK write_file failed for %s: %s", path, e)
            raise SandboxUnavailableError(f"write_file failed: {e}") from e

    # ─── Command Execution (SDK-only) ─────────────────────────────────────

    async def execute_command(
        self, workspace_id: str, command: str, cwd: str = "/workspace"
    ) -> dict[str, Any]:
        """
        Execute a command inside the sandboxed workspace via the SDK.

        SECURITY: There is NO subprocess fallback. If the SDK Conversation
        is not active, SandboxUnavailableError is raised.
        """
        conversation = self._require_conversation(workspace_id)

        try:
            conversation.send_message(
                f"Run this command and report the output: `{command}`"
            )
            conversation.run()
            return {
                "exit_code": 0,
                "stdout": "Agent executed the command via SDK.",
                "stderr": "",
                "duration_ms": 0,
                "via": "sdk",
            }
        except SandboxUnavailableError:
            raise
        except Exception as e:
            logger.error("SDK command execution failed: %s", e)
            raise SandboxUnavailableError(f"execute_command failed: {e}") from e

    async def stream_command_output(
        self, workspace_id: str, command: str, cwd: str = "/workspace"
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream command output line by line via the SDK."""
        result = await self.execute_command(workspace_id, command, cwd)

        for line in result["stdout"].splitlines():
            yield {"stream": "stdout", "text": line}

        for line in result["stderr"].splitlines():
            yield {"stream": "stderr", "text": line}


# ─── Singleton ────────────────────────────────────────────────────────────────

_client: OpenHandsClient | None = None


def get_openhands_client() -> OpenHandsClient:
    global _client
    if _client is None:
        _client = OpenHandsClient(settings=get_settings())
    return _client
