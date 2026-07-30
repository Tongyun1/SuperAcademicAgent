"""M1 skeleton: does a real Stirrup Agent loop run on our gateway via AnthropicMessagesClient?

Runs an agent with one custom tool ('add') + the default finish tool, and checks the
loop actually calls the tool and then finishes.
"""
import asyncio, os, pathlib
from pydantic import BaseModel, Field

# load gateway config from the original project's .env
ENV = pathlib.Path("/mnt/workspace/workgroup5/zhanfeng/SuperAcademicAISearch/.env")
for line in ENV.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from stirrup import Agent, Tool, ToolResult, ToolUseCountMetadata
from saagent import AnthropicMessagesClient


class AddParams(BaseModel):
    a: int = Field(description="first number")
    b: int = Field(description="second number")


def _add(p: AddParams) -> ToolResult[ToolUseCountMetadata]:
    return ToolResult(content=str(p.a + p.b), metadata=ToolUseCountMetadata(), success=True)


ADD_TOOL = Tool[AddParams, ToolUseCountMetadata](
    name="add", description="Add two integers and return the sum.",
    parameters=AddParams, executor=_add,
)


async def main() -> None:
    client = AnthropicMessagesClient(model="qwen3.7-max", max_output_tokens=2048)
    agent = Agent(
        client=client,
        name="skeleton",
        tools=[ADD_TOOL],
        max_turns=50,
        system_prompt="You are a calculator agent. Use the 'add' tool to compute sums; do not compute in your head.",
    )
    async with agent.session(output_dir="results/m1_skeleton") as session:
        finish_params, history, metadata = await session.run(
            "What is 17 + 25? Use the add tool, tell me the result, then finish."
        )
    print("\n=== RESULT ===")
    print("finish reason:", getattr(finish_params, "reason", finish_params))
    tool_calls = [tc.name for msgs in history for m in ([msgs] if not isinstance(msgs, list) else msgs)
                  for tc in getattr(m, "tool_calls", [])]
    print("tool calls seen:", tool_calls)
    print("turns of history:", len(history))


if __name__ == "__main__":
    asyncio.run(main())
