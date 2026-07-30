"""M3 test: does the agent ask the user (with options) when the input is ambiguous?

Replaces the real console ask_user with a stub that records what the model asked
(question + choices) and auto-answers, so the loop runs non-interactively and we can
verify: (a) the model chose to ask, (b) it offered concrete choices, (c) it used the answer.
"""
import asyncio
import json
import os
import pathlib
import sys

ENV = pathlib.Path(__file__).resolve().parents[1] / ".env"
for line in ENV.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from stirrup import Agent, Tool, ToolResult, ToolUseCountMetadata
from stirrup.tools.user_input import UserInputParams

from saagent.build import build_client
from saagent.context import build_context
from saagent.prompts import RESEARCH_AGENT_SYSTEM
from saagent.tools import build_emit_result_tool
from saagent.tools.analysis import build_analysis_tools
from saagent.tools.graph import build_graph_tools
from saagent.tools.seeds import build_seed_tools

ASKED: list[dict] = []


def _stub_ask(p: UserInputParams) -> ToolResult[ToolUseCountMetadata]:
    ASKED.append({"question": p.question, "type": p.question_type, "choices": p.choices})
    # generic auto-answer: pick the first offered option, else a generic free-text reply
    if p.question_type == "choice" and p.choices:
        ans = p.choices[0]
    else:
        ans = "Go with the most prominent / mainstream interpretation in machine learning."
    print(f"\n>>> [STUB ask_user] type={p.question_type}\n    Q: {p.question}\n    choices: {p.choices}\n    -> auto-answer: {ans}\n", flush=True)
    return ToolResult(content=ans, metadata=ToolUseCountMetadata(), success=True)


async def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "SAM"
    slug = "".join(c if c.isalnum() else "_" for c in query)[:20]
    ctx = build_context(query, out_dir=f"results/m3_{slug}", max_nodes=30)
    stub = Tool[UserInputParams, ToolUseCountMetadata](
        name="ask_user",
        description="Ask the user a question when uncertain. Supports question_type 'text'|'choice'|'confirm'; for 'choice' provide a choices list.",
        parameters=UserInputParams,
        executor=_stub_ask,
    )
    tools = [*build_seed_tools(ctx), *build_graph_tools(ctx), *build_analysis_tools(ctx), stub]
    agent = Agent(
        client=build_client(ctx),
        name="researcher",
        tools=tools,
        finish_tool=build_emit_result_tool(ctx),
        system_prompt=RESEARCH_AGENT_SYSTEM,
        max_turns=40,
    )
    try:
        async with agent.session(output_dir=str(ctx.out_dir)) as session:
            await session.run(f"Research this and produce result.json: {query!r}")
    finally:
        await ctx.aclose()

    print("\n================ ASK-USER SUMMARY ================")
    print(f"model called ask_user {len(ASKED)} time(s)")
    for i, a in enumerate(ASKED, 1):
        print(f"  [{i}] type={a['type']} | choices={a['choices']}\n      Q: {a['question']}")
    if ctx.result_path:
        r = json.load(open(ctx.result_path))
        print(f"result: query={r['query']!r} nodes={len(r['graph']['nodes'])} founding={r.get('founding')}")


if __name__ == "__main__":
    asyncio.run(main())
