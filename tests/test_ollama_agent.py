import asyncio
import json

from mobium_evals.ollama_agent import FINISH_TOOL, drive


def scripted(*replies):
    seen = []
    it = iter(replies)

    async def chat(messages, tools):
        seen.append([dict(m) for m in messages])
        return {"message": next(it), "prompt_eval_count": 10, "eval_count": 2}

    return chat, seen


def call(name, **args):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


TOOLS = [{"type": "function", "function": {"name": "app_map", "description": "", "parameters": {}}}, FINISH_TOOL]


def test_a_run_ends_on_finish_with_its_claim():
    calls = []

    async def tool(name, args):
        calls.append(name)
        return json.dumps({"elements": []}), False

    chat, seen = scripted(call("app_map"), call("finish", status="done", answer="60", reason="counted"))
    t = asyncio.run(drive(chat, tool, TOOLS, "How many rows?"))
    assert t.finish.status == "done" and t.finish.answer == "60"
    assert calls == ["app_map"] and t.tool_calls == 2 and t.tool_errors == 0
    assert t.usage == {"input_tokens": 20, "output_tokens": 4}
    # What the tool answered went back to the model, by the tool's name.
    assert seen[1][-1] == {"role": "tool", "tool_name": "app_map", "content": json.dumps({"elements": []})}


def test_a_reply_with_no_call_is_nudged_and_arguments_as_text_are_read():
    async def tool(name, args):
        return "{}", False

    chat, seen = scripted({"role": "assistant", "content": "thinking"},
                          {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "finish",
                           "arguments": json.dumps({"status": "cannot", "reason": "covered"})}}]})
    t = asyncio.run(drive(chat, tool, TOOLS, "Tap it."))
    assert t.finish.status == "cannot" and t.finish.reason == "covered"
    assert seen[1][-1] == {"role": "user", "content": "Call one of the tools, or finish."}


def test_an_invalid_finish_is_an_error_the_model_sees():
    async def tool(name, args):
        return "{}", False

    chat, seen = scripted(call("finish", status="maybe"), call("finish", status="done", reason="ok"))
    t = asyncio.run(drive(chat, tool, TOOLS, "x"))
    assert t.finish.status == "done" and t.tool_errors == 1
    assert "status" in seen[1][-1]["content"]


def test_a_model_that_never_finishes_times_out():
    async def tool(name, args):
        return "{}", False

    chat, _ = scripted(*[call("app_map")] * 5)
    t = asyncio.run(drive(chat, tool, TOOLS, "x", max_turns=5))
    assert t.finish.status == "timeout" and t.tool_calls == 5


def test_three_replies_with_no_call_end_the_trial():
    async def tool(name, args):
        return "{}", False

    chat, _ = scripted(*[{"role": "assistant", "content": "hm"}] * 3)
    t = asyncio.run(drive(chat, tool, TOOLS, "x"))
    assert t.finish.status == "timeout" and t.turns == 3
