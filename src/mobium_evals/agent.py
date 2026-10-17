"""One agent trial: a fixed model driving the device through `mobium mcp`.

The agent gets Mobium's MCP server and nothing else — its claim is its final
answer, as structured output, not a harness tool: a `finish` tool beside
seventy-three `mcp__mobium__` tools was called as `mcp__mobium__finish` in
six trials of six. Nothing else either: no built-in tools, no settings, no CLAUDE.md, no skills, and an
empty working directory. That is the leakage guard — the checks, the defect
log and MobiumApp's source are the answer key, and none of it is reachable.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

from .device import MOBIUM

# One fixed, empty working directory for every trial: nothing in it to read,
# and one Claude Code project entry rather than one per trial.
AGENT_CWD = Path.home() / ".cache/mobium-evals/agent-cwd"
from .tasks import Finish

SYSTEM_PROMPT = """\
You operate a mobile device for the user through the mobium tools. The device \
is already chosen; you do not need to pass one.

Do what the user asks on the device. When you have finished — whether you did \
it, or found that it cannot be done — end with your final answer: status \
"done" if it is done, "cannot" if it cannot be done, an answer if the user \
asked a question, and a one-sentence reason."""

FINISH_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["done", "cannot"]},
        "answer": {
            "type": "string",
            "description": "Only when the user asked a question: the answer itself and nothing else — "
            "a number, a name, or the words quoted. How you know goes in reason.",
        },
        "reason": {"type": "string", "description": "One sentence: what you did, or why it cannot be done."},
    },
    "required": ["status", "reason"],
    "additionalProperties": False,
}


@dataclass
class Trial:
    finish: Finish
    transcript: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: int = 0
    tool_results: list[str] = field(default_factory=list)
    tool_errors: int = 0
    artifacts: list[str] = field(default_factory=list)
    wall_s: float = 0.0
    turns: int | None = None
    usage: dict[str, Any] | None = None
    cost_usd: float | None = None
    tools_offered: list[str] = field(default_factory=list)


def _jsonable(msg: Any) -> dict[str, Any]:
    d = dataclasses.asdict(msg) if dataclasses.is_dataclass(msg) else {"value": msg}
    d["_type"] = type(msg).__name__
    return json.loads(json.dumps(d, default=str))


def _result_text(block: ToolResultBlock) -> str:
    c = block.content
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in c)
    return "" if c is None else str(c)


async def run_agent(
    prompt: str,
    serial: str,
    model: str,
    effort: str,
    max_turns: int = 40,
    wall_s: float = 300,
    artifacts: Path | None = None,
) -> Trial:
    trial = Trial(finish=Finish("timeout"))
    AGENT_CWD.mkdir(parents=True, exist_ok=True)
    if any(AGENT_CWD.iterdir()):
        raise RuntimeError(f"{AGENT_CWD} must stay empty: the agent's working directory is part of the leakage guard")
    options = ClaudeAgentOptions(
        model=model,
        effort=effort,  # type: ignore[arg-type]
        system_prompt=SYSTEM_PROMPT,
        tools=[],
        mcp_servers={
            "mobium": {"type": "stdio", "command": str(MOBIUM), "args": ["mcp", "--device", serial]},
        },
        strict_mcp_config=True,
        allowed_tools=["mcp__mobium"],
        output_format={"type": "json_schema", "schema": FINISH_SCHEMA},
        permission_mode="dontAsk",
        setting_sources=[],
        skills=[],
        cwd=str(AGENT_CWD),
        max_turns=max_turns,
    )
    start = time.monotonic()

    async def consume() -> None:
        async for msg in query(prompt=prompt, options=options):
            trial.transcript.append(_jsonable(msg))
            if isinstance(msg, SystemMessage) and msg.subtype == "init":
                trial.tools_offered = list(msg.data.get("tools", []))
            elif isinstance(msg, AssistantMessage):
                trial.tool_calls += sum(isinstance(b, ToolUseBlock) for b in msg.content)
            elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
                results = [b for b in msg.content if isinstance(b, ToolResultBlock)]
                trial.tool_results += [_result_text(b) for b in results]
                trial.tool_errors += sum(bool(b.is_error) for b in results)
            elif isinstance(msg, ResultMessage):
                trial.turns = msg.num_turns
                trial.usage = msg.usage
                trial.cost_usd = msg.total_cost_usd
                claim = msg.structured_output
                if isinstance(claim, dict) and claim.get("status") in ("done", "cannot"):
                    trial.finish = Finish(claim["status"], claim.get("answer"), claim.get("reason"))

    try:
        await asyncio.wait_for(consume(), timeout=wall_s)
    except TimeoutError:
        trial.transcript.append({"_type": "HarnessTimeout", "after_s": wall_s})
    except Exception as e:  # the SDK or the CLI died: a harness fault, kept
        trial.transcript.append({"_type": "HarnessError", "error": repr(e)})
        trial.finish = Finish("error", reason=repr(e))
    trial.wall_s = round(time.monotonic() - start, 1)
    # What the agent saved through Mobium's tools — a screenshot, a capture —
    # lands here, since `mobium mcp` makes a path absolute where its host
    # runs. It is the trial's evidence: kept with the trial, and the
    # directory emptied for the next.
    for f in list(AGENT_CWD.iterdir()):
        if artifacts is None:
            raise RuntimeError(f"the agent left {f.name} in {AGENT_CWD} and the trial has nowhere to keep it")
        artifacts.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), artifacts / f.name)
        trial.artifacts.append(f.name)

    return trial
