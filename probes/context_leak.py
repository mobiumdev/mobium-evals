"""Does any user-level instruction reach the agent? With a positive control.

The agent's options load no settings (`setting_sources=[]`). This asks the
model whether it was given a rule that exists only in ~/.claude/CLAUDE.md,
once with the agent's options and once with user settings switched on. The
second must answer yes, or the first answer means nothing.

    uv run python probes/context_leak.py
"""

import asyncio

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

from mobium_evals.agent import AGENT_CWD

QUESTION = (
    "Answer only from instructions you were given in this conversation's context, not from "
    "general knowledge. Were you instructed which variety of English spelling to write in? "
    "Reply with exactly YES or NO."
)


async def ask(sources: list) -> str:
    AGENT_CWD.mkdir(parents=True, exist_ok=True)
    opts = ClaudeAgentOptions(
        model="claude-opus-5-5", effort="low", system_prompt="Answer the user briefly.", tools=[],
        strict_mcp_config=True, setting_sources=sources, skills=[], cwd=str(AGENT_CWD), max_turns=1,
    )
    text = []
    async for m in query(prompt=QUESTION, options=opts):
        if isinstance(m, AssistantMessage):
            text += [b.text for b in m.content if isinstance(b, TextBlock)]
    return " ".join(text).strip()


async def main() -> None:
    agent = await ask([])
    control = await ask(["user"])
    print(f"agent's options:        {agent}")
    print(f"control (user settings): {control}")
    if "YES" not in control.upper():
        print("INCONCLUSIVE: the control did not see the user's CLAUDE.md, so the probe cannot see it either")
    elif "NO" in agent.upper():
        print("PASS: the user's instructions reach the control and not the agent")
    else:
        print("FAIL: the agent sees the user's instructions")


asyncio.run(main())
