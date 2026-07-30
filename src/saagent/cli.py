"""CLI: run the SuperAcademic research agent loop end-to-end.

    saagent run "attention is all you need" --out ./results/demo
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# reuse the demo project's Rich renderers + exporter so the agent CLI looks identical
from rich.rule import Rule
from saagent.engine.cli import _print_run_summary, _short_run_id, _splash, console
from saagent.engine.export import export_all

# Cache == raw data (methodology): keep it in a stable, machine-portable location so
# re-runs never re-hit the API. Overridable via --cache-path or SAAS_CACHE_PATH env.
# (Historically hardcoded to the original author's /mnt/... path — not portable.)
_DEFAULT_CACHE = os.getenv("SAAS_CACHE_PATH") or str(
    Path.home() / ".saagent" / "cache" / "superacademic.sqlite"
)

# Secrets (LLM gateway token / OpenAlex key) live OUTSIDE the repo so a scanning
# security/DLP agent doesn't quarantine a repo that contains plaintext
# credentials. Default: ~/.saagent.env, overridable via SAAS_ENV_FILE.
_EXTERNAL_ENV_FILE = os.getenv("SAAS_ENV_FILE") or str(Path.home() / ".saagent.env")


def _load_external_env(path: str = _EXTERNAL_ENV_FILE) -> None:
    """Load a gitignored, out-of-repo `.env` into os.environ (values win).

    Mirrors superacademic.config._load_dotenv but points at a file kept outside
    the repository tree. No-op if the file is absent.
    """
    f = Path(path)
    if not f.is_file():
        return
    try:
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ[key.strip()] = val.strip().strip('"').strip("'")
    except OSError:
        pass


def _sources_status(s) -> str:
    """One-line status of each data source: key / anonymous / off.

    Both API keys are OPTIONAL — the run works without either. OpenAlex is the
    citation-graph backbone (anonymous works, keyed avoids 503 rate limits);
    Semantic Scholar is a citation-count enhancement (degrades to OpenAlex counts
    when off/anonymous/unreachable).
    """
    oa = "key✓" if s.openalex_api_key else ("anon+mailto" if s.mailto else "anon")
    if not getattr(s, "s2_enrich", True):
        s2 = "off"
    else:
        s2 = "key✓" if getattr(s, "s2_api_key", None) else "anon (may rate-limit; set S2_API_KEY)"
    return f"OpenAlex: {oa}  ·  Semantic Scholar: {s2}"


def _print_cover(args, ctx, run_id: str, started_at: datetime) -> None:
    """SUPERACADEMIC splash + agent-loop cover page (mirrors the demo CLI)."""
    console.print()
    console.print(_splash())
    console.print()
    engine = f"{ctx.settings.llm_provider} · {ctx.settings.llm_model or ctx.settings.bailian_model}"
    rows = [
        ("QUERY", args.query),
        ("ENGINE", engine),
        ("MODE", "⊙ AGENT LOOP — autonomous tools · ask-user disambiguation"),
        ("SCOPE", f"max_nodes={args.max_nodes} · lang={args.lang}"
                  f"{' · ask off' if args.no_ask else ''}{' · no-translate' if args.no_translate else ''}"),
        ("SOURCES", _sources_status(ctx.settings)),
    ]
    for k, v in rows:
        console.print(f"  [bold cyan]▸[/bold cyan]  [bold]{k:<7}[/bold]  [white]{v}[/white]")
    console.print()
    console.print(f"  [dim]run #{run_id}   started {started_at:%Y-%m-%d %H:%M:%S}[/dim]")
    console.print(Rule(style="dim cyan"))


async def _run(args: argparse.Namespace) -> int:
    from .build import build_agent
    from .context import build_context

    ctx = build_context(
        args.query,
        out_dir=args.out,
        model=args.model,
        max_nodes=args.max_nodes,
        max_depth=args.depth,
        cache_path=args.cache_path,
    )
    started_at = datetime.now()
    run_id = _short_run_id(args.query, started_at)
    _print_cover(args, ctx, run_id, started_at)

    agent = build_agent(
        ctx,
        model=args.model,
        enable_ask_user=not args.no_ask,
        lang=args.lang,
    )
    t0 = time.time()
    try:
        async with agent.session(output_dir=str(ctx.out_dir)) as session:
            await session.run(f"Research this and produce result.json: {args.query!r}")
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        # API-layer errors (rate limit, auth, bad request from gateway) → show the
        # provider's message directly and exit cleanly, no traceback.
        import anthropic
        from openai import APIError as OpenAIAPIError
        if isinstance(e, (anthropic.APIStatusError, anthropic.APIConnectionError,
                          anthropic.APITimeoutError, OpenAIAPIError)):
            detail = getattr(e, "message", None) or str(e)
            console.print()
            console.print(f"  [bold red]✗ LLM API 错误[/bold red]")
            console.print(f"  [yellow]{detail}[/yellow]")
            console.print()
            console.print("  [dim]可能的原因：API key 额度用尽 / 频率超限 / 网络不通 / 认证失败。[/dim]")
            console.print("  [dim]检查 ~/.saagent.env 中的配置，或等待限流窗口重置后重试。[/dim]")
            console.print()
            return 1
        raise
    finally:
        await ctx.aclose()
    wall = time.time() - t0

    if ctx.result is None:
        console.print("\n  [yellow]⚠  agent finished without calling emit_result — no deliverable.[/yellow]\n")
        return 1

    # localize report -> report.i18n.zh (best-effort) + full export (json / graphml /
    # markdown / png / html), then the demo-style RUN SUMMARY card.
    from .run_export import finalize_result
    exported = finalize_result(ctx, no_translate=args.no_translate)
    _print_run_summary(ctx.result, run_id=run_id, wall_seconds=wall, exported_paths=exported, out_dir=args.out)
    return 0


def _run_pipeline(args: argparse.Namespace) -> int:
    """Deterministic pipeline fallback (no LLM agent loop)."""
    from saagent.engine.core.pipeline import run as pipeline_run
    from saagent.engine.export import export_all

    started_at = datetime.now()
    run_id = _short_run_id(args.query, started_at)

    console.print()
    console.print(_splash())
    console.print()
    console.print(f"  [bold cyan]▸[/bold cyan]  [bold]QUERY  [/bold]  [white]{args.query}[/white]")
    console.print(f"  [bold cyan]▸[/bold cyan]  [bold]MODE   [/bold]  [white]确定性 pipeline（纯图算法，无 LLM）[/white]")
    console.print(f"  [bold cyan]▸[/bold cyan]  [bold]SCOPE  [/bold]  [white]max_nodes={args.max_nodes}[/white]")
    console.print()
    console.print(Rule(style="dim cyan"))

    t0 = time.time()
    try:
        result = pipeline_run(
            args.query,
            max_nodes=args.max_nodes,
            depth=args.depth,
            progress=lambda msg: console.print(f"  [dim]· {msg}[/dim]"),
            llm_provider="null",
        )
    except Exception as e:
        console.print(f"\n  [bold red]✗ pipeline 运行失败: {e}[/bold red]\n")
        return 1
    wall = time.time() - t0

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        exported = export_all(result, str(out_dir))
    except Exception as e:
        console.print(f"  [dim yellow]export skipped: {e}[/dim yellow]")
        exported = None
    _print_run_summary(result, run_id=run_id, wall_seconds=wall, exported_paths=exported, out_dir=args.out)
    return 0


def _preflight_check() -> str:
    """Verify config and determine run mode.

    Returns:
        "agent"    — LLM configured, run the Stirrup agent loop.
        "pipeline" — LLM missing, fall back to deterministic pipeline.
        ""         — env file missing, cannot proceed.
    """
    env_path = Path(_EXTERNAL_ENV_FILE)
    if not env_path.is_file():
        console.print()
        console.print("  [bold red]✗ 配置文件未找到[/bold red]")
        console.print(f"  [yellow]缺少 {env_path}[/yellow]")
        console.print()
        console.print("  [dim]请创建该文件并配置 LLM 后端，示例：[/dim]")
        console.print()
        console.print("  [dim]# 百炼（推荐）[/dim]")
        console.print("  [dim]SAAS_LLM_PROVIDER=bailian[/dim]")
        console.print("  [dim]DASHSCOPE_API_KEY=sk-你的key[/dim]")
        console.print()
        console.print("  [dim]# 或 Anthropic 兼容网关[/dim]")
        console.print("  [dim]SAAS_LLM_PROVIDER=claude[/dim]")
        console.print("  [dim]ANTHROPIC_BASE_URL=https://your-gateway/api[/dim]")
        console.print("  [dim]ANTHROPIC_AUTH_TOKEN=你的token[/dim]")
        console.print()
        console.print("  [dim]不配置大模型也可运行（纯图算法模式），但需要该文件存在。[/dim]")
        console.print(f"  [dim]可执行: touch {env_path}[/dim]")
        console.print()
        return ""

    provider = os.environ.get("SAAS_LLM_PROVIDER", "claude")
    llm_ready = True

    if provider == "bailian":
        if not (os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("SAAS_BAILIAN_API_KEY")):
            llm_ready = False
    elif provider == "local":
        if not os.environ.get("SAAS_LOCAL_BASE_URL"):
            llm_ready = False
    elif provider == "null":
        llm_ready = False
    else:  # claude (default)
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            llm_ready = False

    if not llm_ready:
        console.print()
        console.print("  [yellow]⚠ 未检测到有效的 LLM 配置，将使用确定性 pipeline（纯图算法模式）[/yellow]")
        console.print("  [dim]配置大模型后可获得 AI agent 自主探索 + 领域叙事 + 入门报告。[/dim]")
        console.print()

    # non-blocking warnings for optional but recommended config
    warnings: list[str] = []
    if not (os.environ.get("OPENALEX_API_KEY") or os.environ.get("SAAS_OPENALEX_API_KEY")):
        warnings.append("OPENALEX_API_KEY 未配置，匿名模式下搜索可能被限流")
    for w in warnings:
        console.print(f"  [yellow]⚠ {w}[/yellow]")
    if warnings:
        console.print()

    return "agent" if llm_ready else "pipeline"


def main(argv: list[str] | None = None) -> int:
    _load_external_env()  # pull secrets from ~/.saagent.env before Settings reads os.environ

    # Default subcommand: bare `saagent` or `saagent "<query>"` (no leading run/chat keyword)
    # launches the interactive chat UI instead of requiring an explicit subcommand — argparse
    # subparsers with required=True can't fall through to a default on their own, so rewrite
    # argv before parsing. An explicit leading `run`/`chat` token, or a leading flag (-h/...),
    # bypasses this.
    argv = sys.argv[1:] if argv is None else argv
    known_cmds = {"run", "chat"}
    _chat_flags = {"--continue", "--resume"}
    if not argv or (argv[0] not in known_cmds and not argv[0].startswith("-")):
        argv = ["chat", *argv]
    elif argv[0] in _chat_flags:
        argv = ["chat", *argv]

    parser = argparse.ArgumentParser(prog="saagent", description="SuperAcademic research agent loop")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Run the research agent once on a query (scriptable)")
    run.add_argument("query", help="research direction / paper / fuzzy description / identifier")
    run.add_argument("--out", default="./results/agent_run", help="output directory for result.json")
    run.add_argument("--model", default=None, help="override model slug (default: from .env SAAS_LLM_MODEL)")
    run.add_argument("--max-nodes", type=int, default=60, dest="max_nodes")
    run.add_argument("--depth", type=int, default=2)
    run.add_argument("--cache-path", default=_DEFAULT_CACHE, dest="cache_path",
                     help=f"SQLite cache path (default: {_DEFAULT_CACHE}; or set SAAS_CACHE_PATH)")
    run.add_argument("--no-ask", action="store_true", help="disable the ask_user clarification tool")
    run.add_argument("--lang", choices=["zh", "en"], default="zh",
                     help="language the agent uses to talk to you (ask_user / narration); default zh")
    run.add_argument("--no-translate", action="store_true",
                     help="skip Chinese localization of the report (report.i18n.zh)")

    chat = sub.add_parser("chat", help="Launch the interactive full-screen chat UI (default)")
    chat.add_argument("query", nargs="?", default=None,
                      help="optional first research question (auto-submitted on launch)")
    chat.add_argument("--model", default=None, help="override model slug (default: from .env SAAS_LLM_MODEL)")
    chat.add_argument("--max-nodes", type=int, default=60, dest="max_nodes")
    chat.add_argument("--depth", type=int, default=2)
    chat.add_argument("--cache-path", default=_DEFAULT_CACHE, dest="cache_path",
                      help=f"SQLite cache path (default: {_DEFAULT_CACHE}; or set SAAS_CACHE_PATH)")
    chat.add_argument("--out", default=None,
                      help="session output dir (default: ~/.saagent/sessions/<timestamp>/)")
    chat.add_argument("--lang", choices=["zh", "en"], default="zh",
                      help="language the agent uses to talk to you; default zh")
    chat.add_argument("--no-translate", action="store_true",
                      help="skip Chinese localization of the report (report.i18n.zh)")
    chat.add_argument("--resume", nargs="?", const="__interactive__", default=None,
                      metavar="SESSION_DIR",
                      help="resume a previous session (no arg = interactive list; or pass a session dir path)")
    chat.add_argument("--continue", dest="continue_", action="store_true",
                      help="automatically resume the most recent session")

    args = parser.parse_args(argv)
    if args.cmd == "run":
        mode = _preflight_check()
        if not mode:
            return 1
        if mode == "pipeline":
            return _run_pipeline(args)
        return asyncio.run(_run(args))
    if args.cmd == "chat":
        mode = _preflight_check()
        if not mode:
            return 1
        if mode == "pipeline":
            console.print(
                "  [yellow]⚠ chat UI 需要配置 LLM；请配置后重试，或使用 `saagent run` 走确定性 pipeline。[/yellow]"
            )
            return 1
        from .tui.app import run_chat_app
        return run_chat_app(args)  # sync entry point; owns its own asyncio.run() internally
    return 1


if __name__ == "__main__":
    sys.exit(main())
