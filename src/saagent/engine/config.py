"""Runtime configuration, populated from defaults + environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    """Load a gitignored `.env` (CWD or repo root) into os.environ.

    Zero-dependency. **`.env` values OVERRIDE existing env vars** — `.env` is the
    app's explicit local config, so it must win even when the surrounding session
    already exports ANTHROPIC_* (e.g. an internal gateway you want to override).
    This only affects the current (sub)process. `.env` is gitignored — never commit it.
    """
    candidates = [Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"]
    for f in candidates:
        if not f.is_file():
            continue
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                os.environ[key.strip()] = val.strip().strip('"').strip("'")
        except OSError:
            pass
        break


@dataclass
class Settings:
    # --- Data source (OpenAlex) ---
    openalex_base: str = "https://api.openalex.org"
    mailto: str | None = None  # OpenAlex "polite pool" contact email -> faster, nicer
    openalex_api_key: str | None = None  # free OpenAlex API key -> uninterrupted (anonymous search is rate-limited under load)
    request_timeout: float = 30.0
    max_concurrency: int = 5
    rate_per_sec: float = 8.0  # OpenAlex polite pool tolerates ~10 req/s

    # --- Graph construction defaults ---
    max_depth: int = 2
    max_nodes: int = 200
    # Working collection cap during expansion (defaults to max_nodes*4). Kept larger
    # than max_nodes so late-fetched frontier papers (expand_frontier) still get in
    # before the graph fills; the final graph is trimmed by relevance pruning, not
    # by this cap. Prevents old most-cited papers from squatting all the slots.
    max_collect: int | None = None
    per_node_citations: int = 25  # top-K most-cited citing papers per node
    per_node_recent: int = 10  # additional newest citing papers per node (surfaces frontier)
    per_node_references: int = 25  # top-K references to keep per node
    # broad arXiv topic recall: pull recent same-topic papers citation search misses
    # (off-topic ones are pruned later by relevance tagging)
    arxiv_recall: int = 20
    # survey-first: mine recent surveys and let the LLM curate their references
    # (field-relevant key/frontier works, discarding generic background). LLM-only;
    # no-LLM runs skip it. See core/surveys.py.
    use_surveys: bool = True
    survey_count: int = 3  # how many recent surveys to mine
    survey_refs_per: int = 40  # references to pull from each survey

    # --- Cache ---
    cache_path: str = ".cache/superacademic.sqlite"
    use_cache: bool = True

    # --- Semantic Scholar (citation-count enrichment) ---
    # OpenAlex citation counts can be wrong for some papers (e.g. "Attention Is All
    # You Need" = 6576 vs the real ~182k). S2 by arXiv id / DOI returns accurate
    # counts; we use it to correct citation_count before metrics. Optional API key
    # avoids the aggressive unauthenticated rate limit (HTTP 429).
    s2_enrich: bool = True
    s2_api_key: str | None = None

    # --- LLM ---
    llm_provider: str = "claude"  # "claude" | "bailian" | "local" | "null" (pure graph)
    llm_model: str | None = None
    anthropic_api_key: str | None = None
    anthropic_auth_token: str | None = None
    anthropic_base_url: str | None = None
    llm_max_tokens: int = 16384  # generous output cap: full report + zh translation JSON must not truncate (4096 was too small -> i18n silently empty)
    translate: bool = True  # localize report to zh (slow extra LLM call; off to speed up eval)
    prune_off_topic: bool = True  # drop off-topic nodes from the graph so the network stays clean
    # local OpenAI-compatible model (e.g. vLLM-served Qwen3-8B)
    local_base_url: str | None = None  # e.g. http://localhost:8001/v1
    local_model: str = "qwen3-8b"
    # Bailian / DashScope (Alibaba Cloud) — OpenAI-compatible mode
    bailian_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    bailian_api_key: str | None = None
    bailian_model: str = "qwen3-max"
    bailian_enable_thinking: bool | None = None  # None=omit; True/False=send explicitly

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        _load_dotenv()
        s = cls(
            mailto=os.getenv("SAAS_MAILTO") or os.getenv("OPENALEX_MAILTO"),
            openalex_api_key=os.getenv("OPENALEX_API_KEY") or os.getenv("SAAS_OPENALEX_API_KEY"),
            llm_provider=os.getenv("SAAS_LLM_PROVIDER", "claude"),
            llm_model=os.getenv("SAAS_LLM_MODEL") or os.getenv("ANTHROPIC_MODEL"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            anthropic_auth_token=os.getenv("ANTHROPIC_AUTH_TOKEN"),
            anthropic_base_url=os.getenv("ANTHROPIC_BASE_URL"),
            local_base_url=os.getenv("SAAS_LOCAL_BASE_URL"),
            local_model=os.getenv("SAAS_LOCAL_MODEL", "qwen3-8b"),
            bailian_api_key=os.getenv("DASHSCOPE_API_KEY") or os.getenv("SAAS_BAILIAN_API_KEY"),
            bailian_base_url=os.getenv(
                "SAAS_BAILIAN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
            ),
            bailian_model=os.getenv("SAAS_BAILIAN_MODEL", "qwen3-max"),
            translate=os.getenv("SAAS_TRANSLATE", "1") not in ("0", "false", "False", "no"),
            s2_enrich=os.getenv("SAAS_S2_ENRICH", "1") not in ("0", "false", "False", "no"),
            s2_api_key=os.getenv("S2_API_KEY") or os.getenv("SEMANTICSCHOLAR_API_KEY"),
        )
        for k, v in overrides.items():
            if v is not None and hasattr(s, k):
                setattr(s, k, v)
        return s

    @property
    def llm_available(self) -> bool:
        if self.llm_provider == "null":
            return False
        if self.llm_provider == "local":
            return bool(self.local_base_url)
        if self.llm_provider == "bailian":
            return bool(self.bailian_api_key)
        return bool(self.anthropic_api_key or self.anthropic_auth_token)
