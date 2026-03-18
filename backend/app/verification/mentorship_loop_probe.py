"""
Deterministic Step 5 probe for the mentorship loop.

This exercises the real RunManager/TaskDelegator orchestration with scripted
agent outputs so the probe can force:
  - two QA failures with structured qa:report payloads
  - transition into LEADER_REVIEW
  - leader_guidance.md artifact emission
  - a mentored third Dev attempt that passes QA

It also probes LLMSummarizingCondenser directly to verify history
condensation reduces the event view.

Usage:
  python -m app.verification.mentorship_loop_probe
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any
from uuid import uuid4

from openhands.sdk import LLM, Message, TextContent
from openhands.sdk.context.condenser import LLMSummarizingCondenser
from openhands.sdk.context.view import View
from openhands.sdk.event.base import LLMConvertibleEvent
from pydantic import Field, SecretStr

from ..agents.dev_agent import DevAgentResult
from ..agents.leader_agent import AgentTask, LeaderAgentResult
from ..agents.qa_agent import QaAgentResult, QaCheckResult, QaError, QaScores
from ..db.database import async_session
from ..orchestrator.run_manager import RunManager
from ..services.event_broker import get_event_broker
from ..services.openhands_client import get_openhands_client
from ..services.run_store import RunStore


class DummyLLMEvent(LLMConvertibleEvent):
    source: str = "agent"
    text: str = Field(default="")

    def to_llm_message(self) -> Message:
        return Message(
            role="assistant",
            content=[TextContent(text=self.text)],
        )


class ScriptedLeaderAgent:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(
        self,
        run_id: str,
        goal: str,
        context: dict[str, Any] | None = None,
        llm_config: dict[str, Any] | None = None,
        mentorship_mode: bool = False,
    ) -> LeaderAgentResult:
        self.calls.append(
            {
                "run_id": run_id,
                "goal": goal,
                "mentorship_mode": mentorship_mode,
            }
        )

        if mentorship_mode:
            return LeaderAgentResult(
                status="done",
                summary="Mentorship guidance produced",
                raw_output=(
                    "# Leader Guidance\n\n"
                    "1. Replace the insecure parser with explicit integer parsing.\n"
                    "2. Add a regression test that rejects arbitrary expressions.\n"
                    "3. Avoid eval-like behavior entirely.\n"
                ),
            )

        return LeaderAgentResult(
            status="done",
            tasks=[
                AgentTask(
                    id="task_step5_probe",
                    label="Implement a secure parser and regression test",
                    acceptance_criteria=(
                        "Parser accepts integers, rejects arbitrary expressions, "
                        "and a regression test covers the unsafe case."
                    ),
                )
            ],
            summary="Planned one implementation task",
        )


class ScriptedDevAgent:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(
        self,
        run_id: str,
        goal: str,
        context: dict[str, Any] | None = None,
        llm_config: dict[str, Any] | None = None,
    ) -> DevAgentResult:
        ctx = context or {}
        attempt = int(ctx.get("attempt", 1))
        self.calls.append({"attempt": attempt, "goal": goal})

        runtime = get_openhands_client().get_runtime(ctx.get("workspace_id", "repo-main"))
        if attempt < 3:
            runtime.write_file(
                "/workspace/src/mentor_probe.py",
                "def parse(value):\n    return eval(value)\n",
            )
            return DevAgentResult(
                status="done",
                files_changed=["src/mentor_probe.py"],
                summary=f"Draft implementation attempt {attempt}",
                raw_output=f"attempt-{attempt}-draft",
            )

        runtime.write_file(
            "/workspace/src/mentor_probe.py",
            "def parse(value: str) -> int:\n"
            "    stripped = value.strip()\n"
            "    if not stripped or any(ch not in '-0123456789' for ch in stripped):\n"
            "        raise ValueError('only integer literals are allowed')\n"
            "    return int(stripped)\n",
        )
        runtime.write_file(
            "/workspace/tests/test_mentor_probe.py",
            "from src.mentor_probe import parse\n\n"
            "def test_parse_allows_integer_literal():\n"
            "    assert parse('42') == 42\n\n"
            "def test_parse_rejects_expression():\n"
            "    try:\n"
            "        parse('__import__(\"os\").system(\"calc\")')\n"
            "    except ValueError:\n"
            "        assert True\n"
            "    else:\n"
            "        raise AssertionError('expected ValueError')\n",
        )
        return DevAgentResult(
            status="done",
            files_changed=["src/mentor_probe.py", "tests/test_mentor_probe.py"],
            summary="Applied mentorship guidance and added regression coverage",
            raw_output="attempt-3-fixed",
        )


class ScriptedQaAgent:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(
        self,
        run_id: str,
        task_id: str,
        attempt: int,
        changed_files: list[str],
        context: dict[str, Any] | None = None,
        llm_config: dict[str, Any] | None = None,
    ) -> QaAgentResult:
        self.calls.append(
            {
                "run_id": run_id,
                "task_id": task_id,
                "attempt": attempt,
                "changed_files": changed_files,
            }
        )

        runtime = get_openhands_client().get_runtime((context or {}).get("workspace_id", "repo-main"))

        if attempt < 3:
            runtime.write_file(
                "/workspace/critique_report.md",
                "# QA Critique Report\n\n"
                f"Attempt {attempt} failed because the parser still evaluates "
                "arbitrary expressions and lacks regression coverage.\n",
            )
            return QaAgentResult(
                status="failed",
                task_id=task_id,
                attempt=attempt,
                summary="Security and robustness thresholds failed",
                scores=QaScores(
                    code_quality=68,
                    requirements=74,
                    robustness=52,
                    security=25,
                ),
                failing_command="pytest -q",
                exit_code=1,
                raw_log_tail=["ValueError not raised", "Security risk: eval() usage detected"],
                errors=[
                    QaError(
                        kind="security",
                        file="src/mentor_probe.py",
                        line=2,
                        message="Use of eval() allows arbitrary code execution",
                    )
                ],
                retryable=True,
                commands=[
                    QaCheckResult(
                        command="pytest -q",
                        exit_code=1,
                        stdout="1 failed, 1 passed",
                        stderr="AssertionError: expected ValueError",
                        duration_ms=120,
                    )
                ],
                raw_output='{"status":"failed"}',
            )

        runtime.write_file(
            "/workspace/critique_report.md",
            "# QA Critique Report\n\nAttempt 3 passed all thresholds.\n",
        )
        return QaAgentResult(
            status="passed",
            task_id=task_id,
            attempt=attempt,
            summary="All verification checks passed",
            scores=QaScores(
                code_quality=95,
                requirements=96,
                robustness=94,
                security=98,
            ),
            retryable=False,
            commands=[
                QaCheckResult(
                    command="pytest -q",
                    exit_code=0,
                    stdout="2 passed",
                    stderr="",
                    duration_ms=110,
                )
            ],
            raw_output='{"status":"passed"}',
        )


async def _probe_condenser() -> dict[str, Any]:
    fake_llm = LLM(
        model="openai/gpt-4o",
        api_key=SecretStr("probe"),
        base_url="http://localhost",
        usage_id="condenser-probe",
    )

    def _fake_completion(self: LLM, messages: list[Message], **kwargs: Any) -> Any:
        return SimpleNamespace(
            id="condense_probe_response",
            message=Message(
                role="assistant",
                content=[TextContent(text="Condensed history summary")],
            ),
        )

    fake_llm.completion = MethodType(_fake_completion, fake_llm)

    events = [DummyLLMEvent(text=f"event-{idx}") for idx in range(10)]
    view = View(events=events)
    condenser = LLMSummarizingCondenser(llm=fake_llm, max_size=6, keep_first=1)
    condensation = condenser.get_condensation(view)
    condensed_events = condensation.apply(events)

    assert len(condensed_events) < len(events)
    assert condensation.summary == "Condensed history summary"

    return {
        "forgottenCount": len(condensation.forgotten_event_ids),
        "originalEventCount": len(events),
        "condensedEventCount": len(condensed_events),
        "summary": condensation.summary,
    }


async def _probe_mentorship_loop() -> dict[str, Any]:
    broker = get_event_broker()
    await broker.connect()

    manager = RunManager(broker=broker)
    leader = ScriptedLeaderAgent()
    dev = ScriptedDevAgent()
    qa = ScriptedQaAgent()
    manager._leader_agent = leader
    manager._dev_agent = dev
    manager._qa_agent = qa

    run_id = f"run_step5_{uuid4().hex[:10]}"

    async with async_session() as session:
        await RunStore.create_run(
            session,
            run_id=run_id,
            goal=(
                "Build a secure integer parser, reject arbitrary expressions, "
                "and add regression coverage."
            ),
            workspace_id="repo-main",
        )

    await manager.execute_run(run_id)

    async with async_session() as session:
        snapshot = await RunStore.get_run_snapshot(session, run_id)
        events = await RunStore.get_events_for_run(session, run_id)

    assert snapshot is not None
    assert snapshot["status"] == "completed"

    event_types = [event.type for event in events]
    qa_reports = [event for event in events if event.type == "qa:report"]
    qa_passed = [event for event in events if event.type == "qa:passed"]
    critique_updates = [
        event for event in events
        if event.type == "fs:update" and event.data.get("name") == "critique_report.md"
    ]
    guidance_updates = [
        event for event in events
        if event.type == "fs:update" and event.data.get("name") == "leader_guidance.md"
    ]
    leader_review_states = [
        event for event in events
        if event.type == "run:state" and event.data.get("phase") == "leader-review"
    ]

    assert len(qa_reports) == 2
    assert len(qa_passed) == 1
    assert critique_updates
    assert guidance_updates
    assert leader_review_states
    assert len(dev.calls) == 3
    assert "leader_guidance.md" in dev.calls[2]["goal"]

    runtime = get_openhands_client().get_runtime("repo-main")
    critique_text = runtime.read_file("/workspace/critique_report.md")
    guidance_text = runtime.read_file("/workspace/leader_guidance.md")

    assert "QA Critique Report" in critique_text
    assert "Leader Guidance" in guidance_text

    return {
        "runId": run_id,
        "finalStatus": snapshot["status"],
        "taskCount": len(snapshot["tasks"]),
        "qaReportAttempts": [event.data["attempt"] for event in qa_reports],
        "qaPassedAttempt": qa_passed[0].data["attempt"],
        "leaderReviewSeq": leader_review_states[0].seq,
        "critiqueArtifactSeqs": [event.seq for event in critique_updates],
        "guidanceArtifactSeqs": [event.seq for event in guidance_updates],
        "eventTypes": event_types,
        "devAttemptGoals": [call["goal"] for call in dev.calls],
        "leaderMentorshipCalls": [
            call for call in leader.calls if call["mentorship_mode"]
        ],
        "qaReportShape": qa_reports[0].data,
    }


async def main() -> None:
    condenser_result = await _probe_condenser()
    mentorship_result = await _probe_mentorship_loop()

    print(
        json.dumps(
            {
                "status": "passed",
                "condenser": condenser_result,
                "mentorshipLoop": mentorship_result,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
