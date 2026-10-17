"""The second driver: a local open-weight model through Ollama, driving the
same tasks through the same `mobium mcp`, graded by the same graders.

Claude drives the hillclimb and Claude would propose its patches, so the
tool descriptions could drift toward what one model family reads well,
while Mobium is driven from any MCP client (PLAN.md, "A second driver").
This model's absolute score matters little; its movement under a change
is the check. It is free, and needs no API.

Kept as close to the Claude driver as the two loops allow, so a difference
is the model's: the same system prompt's substance, the same server in
the same empty directory, and a tool's structured answer handed to the
model when there is one — what Claude Code hands its own (CHALLENGES 303).
Ollama has no structured final answer, so the claim is a `finish` tool;
its tools are not namespaced, so the misnaming that ruled that out for
Claude (agent.py) does not arise.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import urllib.request
from pathlib import Path
from typing import Any, Awaitable, Callable

from .agent import AGENT_CWD, FINISH_SCHEMA, Trial
from .device import MOBIUM
from .tasks import Finish

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
# Mobium's 73 tools are about 27,000 tokens: Ollama's default window would
# drop most of them without a word.
NUM_CTX = 40960

SYSTEM_PROMPT = """\
You operate a mobile device for the user through the mobium tools. The device \
is already chosen; you do not need to pass one.

Do what the user asks on the device. When you have finished — whether you did \
it, or found that it cannot be done — call the finish tool exactly once: \
status "done" if it is done, "cannot" if it cannot be done, an answer if the \
user asked a question (the answer itself and nothing else), and a one-sentence \
reason."""

FINISH_TOOL = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": "Report that the task is over, and how it ended. Call it exactly once, last.",
        "parameters": FINISH_SCHEMA,
    },
}

Chat = Callable[[list[dict[str, Any]], list[dict[str, Any]]], Awaitable[dict[str, Any]]]
CallTool = Callable[[str, dict[str, Any]], Awaitable[tuple[str, bool]]]


async def drive(chat: Chat, call_tool: CallTool, tools: list[dict[str, Any]], prompt: str,
                max_turns: int = 40) -> Trial:
    """The loop, with the model and the tools passed in: ask, run what it
    calls, hand back what came back, until it calls finish or the turns run
    out. A reply that calls nothing is nudged, three times at most."""
    trial = Trial(finish=Finish("timeout"))
    trial.tools_offered = [t["function"]["name"] for t in tools]
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
    idle = 0
    for turn in range(max_turns):
        trial.turns = turn + 1
        reply = await chat(messages, tools)
        msg = reply.get("message") or {}
        messages.append(msg)
        trial.transcript.append({"_type": "AssistantMessage", "message": msg})
        usage = trial.usage or {"input_tokens": 0, "output_tokens": 0}
        usage["input_tokens"] += reply.get("prompt_eval_count", 0)
        usage["output_tokens"] += reply.get("eval_count", 0)
        trial.usage = usage
        calls = msg.get("tool_calls") or []
        if not calls:
            idle += 1
            if idle >= 3:
                break
            messages.append({"role": "user", "content": "Call one of the tools, or finish."})
            continue
        idle = 0
        for call in calls:
            fn = call.get("function") or {}
            name, args = fn.get("name", ""), fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            trial.tool_calls += 1
            if name == "finish":
                status = args.get("status")
                if status in ("done", "cannot"):
                    trial.finish = Finish(status, args.get("answer") or None, args.get("reason"))
                    trial.transcript.append({"_type": "Finish", "args": args})
                    return trial
                text, is_error = 'finish needs status "done" or "cannot"', True
            else:
                text, is_error = await call_tool(name, args)
            trial.tool_results.append(text)
            trial.tool_errors += int(is_error)
            messages.append({"role": "tool", "tool_name": name, "content": text})
            trial.transcript.append({"_type": "ToolResult", "name": name, "args": args, "is_error": is_error, "content": text})
    return trial


async def _chat(model: str) -> Chat:
    async def chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        body = json.dumps({"model": model, "messages": messages, "tools": tools, "stream": False,
                           "options": {"num_ctx": NUM_CTX, "temperature": 0.2}}).encode()
        req = urllib.request.Request(f"{OLLAMA}/api/chat", data=body, headers={"content-type": "application/json"})
        return await asyncio.to_thread(lambda: json.load(urllib.request.urlopen(req, timeout=600)))

    return chat


async def run_ollama_agent(prompt: str, serial: str, model: str, max_turns: int = 40, wall_s: float = 900,
                           artifacts: Path | None = None) -> Trial:
    """One trial: `mobium mcp` for this device, the model by its Ollama name
    (`ollama/llama3.1:8b` → `llama3.1:8b`)."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    AGENT_CWD.mkdir(parents=True, exist_ok=True)
    if any(AGENT_CWD.iterdir()):
        raise RuntimeError(f"{AGENT_CWD} must stay empty: the agent's working directory is part of the leakage guard")
    start = time.monotonic()
    trial = Trial(finish=Finish("timeout"))
    params = StdioServerParameters(command=str(MOBIUM), args=["mcp", "--device", serial], cwd=str(AGENT_CWD))
    try:
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                listed = (await session.list_tools()).tools
                tools = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                           "parameters": t.input_schema}} for t in listed]
                tools.append(FINISH_TOOL)

                async def call_tool(name: str, args: dict[str, Any]) -> tuple[str, bool]:
                    try:
                        res = await session.call_tool(name, args)
                    except Exception as e:  # an unknown tool, a bad argument: the model's to see
                        return f"error: {e}", True
                    # What Claude Code hands its model: the structured answer
                    # when there is one, else the text (CHALLENGES 303).
                    if res.structured_content is not None:
                        text = json.dumps(res.structured_content)
                    else:
                        text = "\n".join(getattr(c, "text", "") for c in res.content)
                    return text, bool(res.is_error)

                trial = await asyncio.wait_for(drive(await _chat(model.removeprefix("ollama/")), call_tool, tools,
                                                     prompt, max_turns), timeout=wall_s)
    except TimeoutError:
        trial.transcript.append({"_type": "HarnessTimeout", "after_s": wall_s})
    except Exception as e:  # Ollama or the server died: a harness fault, kept
        trial.transcript.append({"_type": "HarnessError", "error": repr(e)})
        trial.finish = Finish("error", reason=repr(e))
    trial.wall_s = round(time.monotonic() - start, 1)
    trial.cost_usd = 0.0
    for f in list(AGENT_CWD.iterdir()):
        if artifacts is None:
            raise RuntimeError(f"the agent left {f.name} in {AGENT_CWD} and the trial has nowhere to keep it")
        artifacts.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), artifacts / f.name)
        trial.artifacts.append(f.name)
    return trial
