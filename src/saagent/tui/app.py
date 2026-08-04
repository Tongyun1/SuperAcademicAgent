"""Persistent chat session — saagent's Claude-Code-style CLI, built on prompt_toolkit.

Bootstraps a RunContext/Agent/session on the FIRST submitted message (Workspace(query, ...)
needs a real query, so there's no valid empty placeholder to construct with at launch), then
reuses that same ctx/agent/session for every subsequent turn so the citation graph keeps
growing turn-to-turn. Full conversation message history is threaded across turns too (see
ConversationState) for genuine LLM memory, not just tool-queryable graph state.

Finished output prints straight into REAL terminal scrollback (via Rich's console.print,
routed through prompt_toolkit's patch_stdout()); only a slim bottom toolbar + single-line
input are "live" at the bottom of the terminal. This is the deliberate architectural choice
over the earlier Textual full-screen version, which switched into the terminal's alternate-
screen buffer and felt like "a layer on top of the terminal" rather than being inside it.
"""

from __future__ import annotations

import asyncio
import io
import itertools
import shutil
import time
from datetime import datetime

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from rich.console import Console as _RenderConsole
from rich.rule import Rule
from stirrup import ChatMessage, SystemMessage, UserMessage

from ..build import build_agent
from ..context import RunContext, build_context
from ..engine.cli import _fmt_wall, _short_run_id, _splash, build_run_summary_renderable, console
from ..naming import default_out_dir
from ..run_export import finalize_result
from .ask_user_bridge import PendingQuestion, build_ask_user_tool, resolve_answer, wants_custom_input
from .logger import ChatAgentLogger, RunawayLoopError
from .render import (
    render_answer_echo,
    render_question_prompt,
    render_system_note,
    render_user_message,
)
from .session_store import list_sessions, load_session, restore_results, restore_workspace, save_session

_BLINK_PERIOD = 0.5  # seconds per on/off half-cycle of the bottom-toolbar "⏺" bullet


def _fmt_tokens(n: int) -> str:
    if n < 1000:
        return f"{n} tokens"
    if n < 10000:
        return f"{n / 1000:.1f}k tokens"
    return f"{n // 1000}k tokens"


class ConversationState:
    """Threads the flattened, SystemMessage-stripped message history across turns.

    Agent.run() prepends a fresh SystemMessage every call, so feeding a history that
    already contains one back in as init_msgs would double it up — strip it before
    handing the history back for the next turn.
    """

    def __init__(self) -> None:
        self._history: list[ChatMessage] = []

    def build_init_msgs(self, new_text: str) -> str | list[ChatMessage]:
        if not self._history:
            return new_text
        return [*self._history, UserMessage(content=new_text)]

    def absorb(self, full_msg_history: list[list[ChatMessage]]) -> None:
        flat = list(itertools.chain.from_iterable(full_msg_history))
        self._history = [m for m in flat if not isinstance(m, SystemMessage)]


class ChatSession:
    """The persistent chat loop: real terminal scrollback + a live bottom toolbar/input."""

    def __init__(self, args) -> None:
        self._args = args
        self._ctx: RunContext | None = None
        self._agent = None
        self._agent_session = None
        self._logger: ChatAgentLogger | None = None
        self._conversation: ConversationState | None = None
        self._pending_question: PendingQuestion | None = None
        self._awaiting_custom_text = False
        self._turn_task: asyncio.Task | None = None
        self._turn_started_at: float | None = None
        self._phase_started_at: float | None = None
        self._active_tool: str | None = None
        self._run_id: str = ""
        self._turn_index = 0
        self._created_at: str | None = None
        self._pt_session: PromptSession | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._verbose_output = False

    def _build_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("c-o")
        def _toggle_verbose(event) -> None:  # noqa: ANN001 — prompt_toolkit's KeyPressEvent
            self._verbose_output = not self._verbose_output
            state = "on" if self._verbose_output else "off"
            console.print(render_system_note(f"verbose tool output: {state} (future tool results only)"))

        @kb.add("escape", eager=True)
        def _cancel_turn(event) -> None:  # noqa: ANN001
            if self._turn_task is not None and not self._turn_task.done():
                self._turn_task.cancel()
                console.print(render_system_note("⏹ 已中断当前任务"))

        return kb

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._pt_session = PromptSession(
            bottom_toolbar=self._render_input_bottom_rule,
            refresh_interval=0.3,
            key_bindings=self._build_key_bindings(),
            erase_when_done=True,
            # the bottom rule is a plain framing line, not prompt_toolkit's default
            # reverse-video status bar — drop the inverted background.
            style=Style.from_dict({"bottom-toolbar": "noreverse bg:default"}),
        )

        with patch_stdout(raw=True):
            self._print_startup_cover()

            # --continue / --resume: restore a previous session
            session_dir = self._resolve_resume_target()
            if session_dir:
                try:
                    await self._bootstrap_from_session(session_dir)
                except (FileNotFoundError, ValueError) as e:
                    console.print(render_system_note(f"✗ resume failed: {e}"))
            elif self._args.query:
                console.print()
                console.print(render_user_message(self._args.query))
                self._turn_task = asyncio.create_task(self._bootstrap_and_run(self._args.query))

            while True:
                try:
                    text = await self._pt_session.prompt_async(self._prompt_message)
                except (KeyboardInterrupt, EOFError):
                    break
                if await self._dispatch(text):
                    break

        await self._shutdown()

    def _print_startup_cover(self) -> None:
        """Splash + engine/sources banner at chat launch (mirrors `saagent run`'s cover).

        The RunContext is bootstrapped lazily on the first message, so build a throwaway
        Settings here just to surface the engine + data-source modes up front — the same
        startup log the one-shot `run` path shows, which chat was previously missing.
        """
        from ..cli import _sources_status  # lazy: cli imports this module at dispatch time
        from ..engine.config import Settings

        console.print()
        console.print(_splash())
        console.print()
        try:
            s = Settings.from_env(llm_model=self._args.model)
        except Exception:  # noqa: BLE001 — never let a config hiccup block the chat launch
            s = None
        if s is not None:
            engine = f"{s.llm_provider} · {s.llm_model or s.bailian_model}"
            rows = [
                ("ENGINE", engine),
                ("MODE", "⊙ CHAT — persistent research session · ask-user disambiguation"),
                ("SOURCES", _sources_status(s)),
            ]
            for k, v in rows:
                console.print(f"  [bold cyan]▸[/bold cyan]  [bold]{k:<7}[/bold]  [white]{v}[/white]")
            console.print()
        console.print("  [dim]输入研究问题开始  ·  /help 查看命令  ·  /quit 退出[/dim]")
        console.print(Rule(style="dim cyan"))

    def _term_width(self) -> int:
        try:
            return self._pt_session.app.output.get_size().columns
        except Exception:  # noqa: BLE001 — fall back to the OS view before the app is live
            return shutil.get_terminal_size((80, 24)).columns

    def _input_rule(self) -> str:
        # A full-width horizontal rule (Claude-Code's input frame). Rendered via a throwaway
        # Rich console so its dim styling turns into raw ANSI we can splice into prompt text.
        width = max(self._term_width(), 1)
        buf = io.StringIO()
        _RenderConsole(file=buf, force_terminal=True, color_system="standard", width=width).print(
            "─" * width, style="dim cyan", end=""
        )
        return buf.getvalue()

    def _render_input_bottom_rule(self) -> ANSI:
        return ANSI(self._input_rule())

    def _prompt_message(self) -> ANSI:
        # Claude-Code layout: the live "thinking / running a tool" status renders ABOVE the
        # framed input. The frame is a top rule (here, in the prompt message) + the "❯ " input
        # line + a bottom rule (the bottom_toolbar), so the input sits between two lines.
        prefix = self._render_status_line()
        top = self._input_rule()
        if self._awaiting_custom_text:
            body = "Your answer (free text) ❯ "
        elif self._pending_question is not None:
            body = "Answer (number/text/Enter=default) ❯ "
        else:
            body = "❯ "
        return ANSI(f"{prefix}{top}\n{body}")

    def _set_active_tool(self, name: str | None) -> None:
        self._active_tool = name
        self._phase_started_at = time.time()

    def _render_status_line(self) -> str:
        if self._pending_question is not None or self._awaiting_custom_text:
            return ""
        if self._turn_started_at is None:
            return ""
        phase_start = self._phase_started_at or self._turn_started_at
        elapsed = time.time() - phase_start
        blink_on = int(elapsed / _BLINK_PERIOD) % 2 == 0
        bullet_style = "bold green" if blink_on else "dim green"
        buf = io.StringIO()
        _RenderConsole(file=buf, force_terminal=True, color_system="standard", width=2).print(
            "⏺", style=bullet_style, end=""
        )
        bullet = buf.getvalue()
        tokens_str = ""
        if self._logger and self._logger.turn_output_tokens:
            tokens_str = f"  [{_fmt_tokens(self._logger.turn_output_tokens)}]"
        if self._active_tool:
            return f"  ⎿ {bullet} {self._active_tool}…  {_fmt_wall(elapsed)}{tokens_str}\n"
        return f"{bullet} thinking…  {_fmt_wall(elapsed)}{tokens_str}\n"

    # ------------------------------------------------------------------
    # ask_user bridge entry point — invoked via loop.call_soon_threadsafe from the
    # anyio worker thread running the sync ask_user_executor (see ask_user_bridge.py).
    # ------------------------------------------------------------------

    def present_question(self, pending: PendingQuestion) -> None:
        self._pending_question = pending
        self._awaiting_custom_text = False
        console.print()
        console.print(render_question_prompt(pending.question, pending.choices))
        if self._pt_session is not None:
            self._pt_session.app.invalidate()

    def _maybe_capture_topic(self, answer: str) -> None:
        # While research hasn't committed a seed yet, the topic anchor (ws.query) is still
        # provisional. If the REAL research topic arrives as an ask_user answer — e.g. the
        # session opened with "你好" and the agent asked what to research mid-turn — capture
        # it here, so relevance/founding/roadmap/report anchor on the real topic instead of
        # the opener. v1.21 only tracks a turn's OPENING text and can't see a mid-turn answer;
        # this is the other half of that fix. Once a seed is committed the anchor locks.
        answer = (answer or "").strip()
        if answer and self._ctx is not None and not self._ctx.ws.seeds:
            self._ctx.ws.query = answer

    def _on_answer_submitted(self, raw: str) -> None:
        pending = self._pending_question
        if self._awaiting_custom_text:
            if not raw:
                console.print(render_system_note("type your answer, or Ctrl+C to cancel"))
                return
            self._awaiting_custom_text = False
            self._pending_question = None
            console.print(render_answer_echo(raw))
            self._maybe_capture_topic(raw)
            pending.future.set_result(raw)
            return

        if wants_custom_input(pending, raw):
            self._awaiting_custom_text = True
            console.print(render_system_note("type your own answer below"))
            return

        answer = resolve_answer(pending, raw)
        self._pending_question = None
        console.print(render_answer_echo(answer))
        self._maybe_capture_topic(answer)
        pending.future.set_result(answer)

    # ------------------------------------------------------------------
    # Input dispatch: new chat message / slash command / answering a pending question.
    # Returns True when the session should end.
    # ------------------------------------------------------------------

    async def _dispatch(self, raw: str) -> bool:
        if self._pending_question is not None:
            self._on_answer_submitted(raw.strip())
            return False

        text = raw.strip()
        if not text:
            return False

        if text.startswith("/"):
            return await self._handle_slash(text)

        if self._turn_task is not None and not self._turn_task.done():
            console.print(render_system_note("agent is still working on the previous message — please wait"))
            return False

        console.print()
        console.print(render_user_message(text))
        if self._ctx is None:
            self._turn_task = asyncio.create_task(self._bootstrap_and_run(text))
        else:
            self._turn_task = asyncio.create_task(self._run_turn(text))
        return False

    async def _handle_slash(self, text: str) -> bool:
        cmd = text.split()[0].lower()
        if cmd == "/new":
            self._turn_task = asyncio.create_task(self._handle_new())
        elif cmd == "/quit":
            return True
        elif cmd == "/help":
            help_text = (
                "[bold]命令[/bold]\n"
                "  /new          开始新的研究方向（清空当前图谱）\n"
                "  /quit         退出\n"
                "  /help         显示此帮助\n"
                "\n"
                "[bold]快捷键[/bold]\n"
                "  Ctrl+O        展开/折叠工具输出详情\n"
                "  Ctrl+C        中断当前任务 / 退出\n"
                "  Ctrl+D        退出\n"
                "\n"
                "[bold]自然语言指令（直接输入即可）[/bold]\n"
                "  研究方向      输入主题/论文标题/DOI/arXiv链接，agent 自动开始分析\n"
                "  改输出目录    \"把结果放到 ./results/demo\"\n"
                "  改参数        \"最大50篇\" / \"用英文\" / \"不要翻译\"\n"
                "  查看配置      \"当前配置是什么\" / \"输出目录在哪\"\n"
                "  追问/扩展     \"再深入一点\" / \"加更多最新论文\" / \"这个方向的前沿是什么\"\n"
                "  精读论文      \"精读 founding paper\" / \"读一下这篇的 method\"\n"
                "  沉淀笔记      \"沉淀\" / \"保存笔记\" → 导出 reading_notes.md\n"
                "\n"
                "[bold]会话恢复[/bold]\n"
                "  --continue    自动恢复最近一次会话 (saagent --continue)\n"
                "  --resume      交互式选择历史会话恢复 (saagent --resume)\n"
                "  --resume DIR  指定会话目录恢复 (saagent --resume ~/saagent-results/...)\n"
                "\n"
                "[bold]输出[/bold]\n"
                "  结果默认保存在 ~/saagent-results/<研究方向>/\n"
                "  包含: result.json · view.html · report.md · citation_network.graphml\n"
                "  精读后: reading_notes.md"
            )
            console.print(render_system_note(help_text))
        else:
            console.print(render_system_note(f"unknown command: {cmd}  (try /new, /quit, /help)"))
        return False

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def _resolve_out_dir(self, query: str = "") -> str:
        if self._args.out:
            return self._args.out
        # Name the session dir after the research direction (query slug) so the
        # result is findable at a glance — e.g. ~/saagent-results/触觉世界模型/
        return default_out_dir(query or "research")

    def _resolve_resume_target(self) -> str | None:
        """Determine session dir to resume from --continue or --resume flags."""
        if getattr(self._args, "continue_", False):
            sessions = list_sessions()
            if not sessions:
                console.print(render_system_note("no previous sessions found"))
                return None
            return sessions[0]["path"]

        resume = getattr(self._args, "resume", None)
        if resume is None:
            return None

        if resume == "__interactive__":
            sessions = list_sessions()
            if not sessions:
                console.print(render_system_note("no previous sessions found"))
                return None
            console.print()
            console.print("[bold]最近会话:[/bold]")
            for i, s in enumerate(sessions[:10], 1):
                ts = s["updated_at"][:16].replace("T", " ") if s["updated_at"] else "?"
                console.print(f"  [cyan]{i}.[/cyan] [{ts}] {s['query'][:40]} — {s['node_count']} nodes, {s['turn_count']} turns")
            console.print()
            try:
                choice = input("输入序号恢复 (q 取消): ").strip()
            except (EOFError, KeyboardInterrupt):
                return None
            if choice.lower() == "q" or not choice:
                return None
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(sessions[:10]):
                    return sessions[idx]["path"]
            except ValueError:
                pass
            console.print(render_system_note("invalid choice"))
            return None

        # resume is a path
        return resume

    async def _bootstrap_from_session(self, session_dir: str) -> None:
        """Restore a full session from session.json — workspace, results, conversation."""
        saved = load_session(session_dir)
        saved_args = saved.get("args", {})

        query = saved["workspace"]["query"]
        self._ctx = build_context(
            query,
            out_dir=session_dir,
            model=self._args.model or saved_args.get("model"),
            max_nodes=saved_args.get("max_nodes", 60),
            max_depth=saved_args.get("depth", 2),
            cache_path=getattr(self._args, "cache_path", None),
        )

        restore_workspace(self._ctx, saved)
        restore_results(self._ctx, saved)

        self._run_id = saved.get("run_id") or _short_run_id(query, datetime.now())
        self._turn_index = saved.get("turn_count", 0)
        self._created_at = saved.get("created_at")

        ask_tool = build_ask_user_tool(self)
        lang = saved_args.get("lang", "zh")
        self._logger = ChatAgentLogger(verbose_getter=lambda: self._verbose_output, status_setter=self._set_active_tool)
        self._agent = build_agent(
            self._ctx,
            model=self._args.model or saved_args.get("model"),
            enable_ask_user=True,
            lang=lang,
            logger=self._logger,
            ask_user_tool=ask_tool,
        )
        self._agent_session = self._agent.session(output_dir=str(self._ctx.out_dir))
        await self._agent_session.__aenter__()

        # Restore conversation history
        from stirrup import AssistantMessage, ToolMessage

        self._conversation = ConversationState()
        msg_types = {"user": UserMessage, "assistant": AssistantMessage, "tool": ToolMessage, "system": SystemMessage}
        history = []
        for m in saved.get("conversation", []):
            role = m.get("role", "user")
            cls = msg_types.get(role)
            if cls:
                try:
                    history.append(cls.model_validate(m))
                except Exception:
                    pass
        self._conversation._history = history

        # Print resume summary
        n_papers = len(self._ctx.ws.papers)
        n_notes = len(self._ctx.reading_notes)
        notes_info = f", {n_notes} notes" if n_notes else ""
        console.print(render_system_note(
            f"✓ 已恢复会话: {query[:50]}\n"
            f"  {n_papers} papers, {len(self._ctx.founding)} founding, "
            f"{self._turn_index} turns{notes_info}\n"
            f"  session: {session_dir}"
        ))

    def _save_session(self) -> None:
        """Best-effort save of current session state."""
        if self._ctx is None or self._conversation is None:
            return
        try:
            save_session(
                self._ctx,
                self._conversation._history,
                args=self._args,
                turn_count=self._turn_index,
                run_id=self._run_id,
                created_at=self._created_at,
            )
        except Exception:
            pass

    async def _bootstrap_and_run(self, first_text: str) -> None:
        out_dir = self._resolve_out_dir(first_text)
        self._ctx = build_context(
            first_text,
            out_dir=out_dir,
            model=self._args.model,
            max_nodes=self._args.max_nodes,
            max_depth=self._args.depth,
            cache_path=self._args.cache_path,
        )
        self._run_id = _short_run_id(first_text, datetime.now())
        self._turn_index = 0
        self._created_at = datetime.now().isoformat(timespec="seconds")
        ask_tool = build_ask_user_tool(self)
        self._logger = ChatAgentLogger(verbose_getter=lambda: self._verbose_output, status_setter=self._set_active_tool)
        self._agent = build_agent(
            self._ctx,
            model=self._args.model,
            enable_ask_user=True,
            lang=self._args.lang,
            logger=self._logger,
            ask_user_tool=ask_tool,
        )
        self._agent_session = self._agent.session(output_dir=str(self._ctx.out_dir))
        await self._agent_session.__aenter__()
        self._conversation = ConversationState()
        await self._run_turn(first_text)

    async def _run_turn(self, text: str) -> None:
        # Topic anchor (ws.query) is provisional until research actually begins: while
        # no seed is committed, keep it tracking the latest user message so an opening
        # "你好" doesn't get frozen in as the research topic (the lazy bootstrap builds
        # the Workspace from the FIRST message, whatever it is). Once a seed is added the
        # anchor locks — from there set_topic governs any change, and follow-up turns on
        # the accumulating graph must not clobber it.
        if self._ctx is not None and not self._ctx.ws.seeds:
            self._ctx.ws.query = text

        self._turn_started_at = time.time()
        self._phase_started_at = self._turn_started_at
        self._active_tool = None
        if self._logger is not None:
            self._logger.reset_runaway_counter()
        result_before = self._ctx.result
        try:
            init_msgs = self._conversation.build_init_msgs(text)
            finish_params, full_msg_history, _run_metadata = await self._agent_session.run(init_msgs)
            self._conversation.absorb(full_msg_history)
            self._active_tool = None

            if finish_params is None:
                console.print(render_system_note(
                    "⚠ 步数用尽 — 你可以继续追问或换一个问题"
                ))
            elif self._ctx.result is not None and self._ctx.result is not result_before:
                exported = finalize_result(self._ctx, no_translate=self._args.no_translate)
                self._turn_index += 1
                run_id = f"{self._run_id}-{self._turn_index}"
                wall = time.time() - self._turn_started_at
                console.print(build_run_summary_renderable(
                    self._ctx.result, run_id=run_id, wall_seconds=wall,
                    exported_paths=exported, out_dir=str(self._ctx.out_dir),
                ))
        except RunawayLoopError:
            # Auto-abort already printed a note; make sure auto-mode is off so the
            # next turn starts clean, and drop any partial history from this turn.
            if self._ctx is not None:
                self._ctx.set_research_mode(False)
        except asyncio.CancelledError:
            # ESC pressed — turn cancelled cleanly; keep session alive
            pass
        except Exception as e:  # noqa: BLE001 — surface the error inline, keep the session alive
            console.print(render_system_note(f"✗ error: {e}"))
        finally:
            if self._logger and self._logger.turn_output_tokens:
                session_out = self._logger.total_output_tokens + self._logger.turn_output_tokens
                console.print(render_system_note(
                    f"tokens: {_fmt_tokens(self._logger.turn_output_tokens)} this turn · "
                    f"session: {_fmt_tokens(session_out)} "
                    f"(input this turn: {_fmt_tokens(self._logger.turn_input_tokens)})"
                ))
                self._logger.reset_turn_tokens()
            self._turn_started_at = None
            self._phase_started_at = None
            self._active_tool = None
            self._save_session()

    async def _handle_new(self) -> None:
        if self._agent_session is not None:
            try:
                await self._agent_session.__aexit__(None, None, None)
            except Exception:
                pass
        if self._ctx is not None:
            await self._ctx.aclose()
        self._ctx = None
        self._agent = None
        self._agent_session = None
        self._conversation = None
        self._pending_question = None
        console.print(render_system_note("started a new research topic — what should I explore?"))

    # ------------------------------------------------------------------
    # Clean shutdown
    # ------------------------------------------------------------------

    async def _shutdown(self) -> None:
        self._save_session()
        if self._pending_question is not None:
            self._pending_question.future.set_exception(KeyboardInterrupt())
            self._pending_question = None
        if self._turn_task is not None and not self._turn_task.done():
            self._turn_task.cancel()
        if self._agent_session is not None:
            try:
                await self._agent_session.__aexit__(None, None, None)
            except Exception:
                pass
        if self._ctx is not None:
            try:
                await self._ctx.aclose()
            except Exception:
                pass
            self._ctx = None


def run_chat_app(args) -> int:
    asyncio.run(ChatSession(args).run())
    console.print("[dim]saagent chat session ended.[/dim]")
    return 0
