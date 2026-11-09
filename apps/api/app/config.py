from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://atlas:atlas@localhost:5432/atlas"
    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "INFO"

    # Must match the model the worker embedded the symbols with.
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    # Longest snippet returned for one symbol, and sent to Claude, in lines.
    snippet_max_lines: int = 80

    # Which model provider answers /ask.
    llm_provider: Literal["anthropic", "gemini"] = "anthropic"

    gemini_api_key: str | None = None
    # Tried in order; the next is used when one is overloaded or over quota.
    gemini_models: str = "gemini-flash-latest,gemini-3.5-flash,gemini-flash-lite-latest"
    gemini_max_tokens: int = 16000

    # Unset means the Anthropic SDK resolves credentials itself (environment or profile).
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "medium"
    anthropic_max_tokens: int = 16000

    # --- The assistant: the chat that answers anything (see app/assistant) ---------
    # Every service below is used once its key is set; all have free tiers. Model
    # lists are comma-separated and tried in order; the router puts coding models
    # first for code and reasoning models for reasoning.
    groq_api_key: str | None = None  # console.groq.com/keys
    groq_models: str = "openai/gpt-oss-120b,openai/gpt-oss-20b"
    openrouter_api_key: str | None = None  # openrouter.ai/keys
    # "auto": every free model in OpenRouter's public catalogue (it changes often).
    openrouter_models: str = "auto"
    mistral_api_key: str | None = None  # console.mistral.ai/api-keys
    mistral_models: str = "mistral-large-latest,mistral-medium-latest,codestral-latest"
    cerebras_api_key: str | None = None  # cloud.cerebras.ai
    cerebras_models: str = "gpt-oss-120b,llama-3.3-70b,qwen-3-32b"
    # A GitHub token with the "Models" permission (github.com/settings/tokens).
    github_models_token: str | None = None
    github_models_models: str = (
        "openai/gpt-4.1,openai/gpt-4.1-mini,meta/Llama-3.3-70B-Instruct,deepseek/DeepSeek-V3-0324"
    )
    cloudflare_account_id: str | None = None  # dash.cloudflare.com → Workers AI
    cloudflare_api_token: str | None = None
    cloudflare_models: str = (
        "@cf/meta/llama-3.3-70b-instruct-fp8-fast,@cf/qwen/qwq-32b,"
        "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b"
    )
    huggingface_api_key: str | None = None  # huggingface.co/settings/tokens
    huggingface_models: str = (
        "meta-llama/Llama-3.3-70B-Instruct,Qwen/Qwen2.5-72B-Instruct,deepseek-ai/DeepSeek-V3-0324"
    )
    sambanova_api_key: str | None = None  # cloud.sambanova.ai
    sambanova_models: str = "DeepSeek-V3.2,gpt-oss-120b,Meta-Llama-3.3-70B-Instruct,MiniMax-M3"
    deepseek_api_key: str | None = None  # platform.deepseek.com (paid, very cheap)
    deepseek_models: str = "deepseek-chat,deepseek-reasoner"
    nvidia_api_key: str | None = None  # build.nvidia.com
    nvidia_models: str = (
        "nvidia/nemotron-3.5-super-vl-120b-a12b,nvidia/nemotron-3-ultra-550b-a55b,"
        "minimaxai/minimax-m3.1-flash,stepfun-ai/step-5-preview,nvidia/nemotron-3.5-lightning-30b-a3b"
    )
    cohere_api_key: str | None = None  # dashboard.cohere.com/api-keys
    cohere_models: str = "command-a-03-2025"
    together_api_key: str | None = None  # api.together.ai
    together_models: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free"
    # Free without any key.
    pollinations_text: bool = True
    pollinations_text_models: str = "openai-fast"
    # AI Horde: volunteers' machines; anonymous use ("0000000000") is free but slow.
    horde_enabled: bool = True
    horde_api_key: str = "0000000000"
    horde_text_models: str = "google/gemma-4-31b"
    # One picture agent per model, drawn in parallel. Anonymous requests wait behind
    # everyone with kudos; a free key from https://aihorde.net/register moves them up.
    horde_image_models: str = "AlbedoBase XL (SDXL),Juggernaut XL,Deliberate"

    # How many of one provider's models to try before moving to the next provider.
    assistant_models_per_provider: int = 2
    # "Best model + fallbacks" order, strongest first.
    assistant_best_order: str = (
        "claude,gemini,deepseek,openrouter,github,mistral,cerebras,groq,sambanova,nvidia,"
        "cohere,huggingface,cloudflare,together,pollinations,horde"
    )
    # The council: this many agents answer each question in parallel and one model
    # merges their best points. 1 turns the council off (one model answers).
    assistant_council_size: int = 12
    # Once two agents have answered, wait this many more seconds for the rest.
    assistant_council_grace: float = 4.0
    # And never wait longer than this for the panel (the first answer is waited for).
    assistant_council_max_wait: float = 35.0
    # Services that merge the drafts first when one of their models answered: the quickest,
    # since the merged answer is what the user waits for.
    assistant_fast_mergers: str = "groq,cerebras"
    # After those, the agents that answered merge in order of how quickly they wrote
    # their own draft.
    assistant_merge_by_speed: bool = True
    # At most this many drafts go to the merge (the best-suited agents' first).
    assistant_merge_drafts: int = 5
    # Search the web before every answer (except small talk) and give every agent the
    # results, so answers carry today's facts. Gemini also searches Google itself (its
    # search quota is separate; refused, it answers without).
    assistant_web_search: bool = True
    # Google News and Wikipedia need no key; Tavily (1,000 free searches a month) and
    # Brave Search add whole-web results when their key is set.
    web_news: bool = True
    web_wikipedia: bool = True
    tavily_api_key: str | None = None  # https://app.tavily.com
    brave_api_key: str | None = None  # https://brave.com/search/api
    web_max_wait: float = 5.0
    # Before a knowledge-base search, a fast model plans several queries (the question,
    # its keywords, a hypothetical answer for HyDE, a variant) whose results are fused.
    assistant_query_planner: bool = True
    # Then fast models judge each candidate excerpt's relevance (0-10, the user's judge
    # prompt); the excerpts are reordered by it and those under the cut-off left out.
    assistant_reranker: bool = True
    assistant_rerank_cutoff: int = 4
    # Excerpts given to the answer model when the question does not say.
    assistant_top_k: int = 5
    # The retrieval core (app/retrieval): 3, 5 or 8 excerpts by the kind of question when
    # the request gives no top_k (never more than 8); a final ranking by rerank, rank
    # fusion, trust, freshness and the source's record, not similarity alone; a budget in
    # seconds for the planner and the judge, past which retrieval carries on without them
    # and the answer is marked degraded; and a cache of retrievals, kept an hour.
    retrieval_adaptive_top_k: bool = True
    retrieval_weighted_rank: bool = False  # off: it lowered top-1 hits in the eval
    retrieval_plan_budget: float = 6.0
    retrieval_judge_budget: float = 12.0
    retrieval_cache: bool = True
    # A cross-encoder reranks the top 20 candidates and keeps 5 (app/retrieval/reranker.py).
    # ATLAS_RERANK=on|off, off until its A/B finishes. It needs about 570 MB (int8) to
    # 2.3 GB (fp32): not the 512 MB free server. The timeout is the spec's, for a GPU; on a
    # CPU raise it, or the stage always degrades to the RRF order.
    atlas_rerank: str = "off"
    atlas_rerank_model: str = "BAAI/bge-reranker-v2-m3"
    atlas_rerank_onnx_repo: str = "onnx-community/bge-reranker-v2-m3-ONNX"
    atlas_rerank_precision: str = "fp32"  # or int8
    atlas_rerank_max_length: int = 512
    atlas_rerank_timeout_ms: int = 150
    # At start the model is loaded and run this many times on dummy pairs, so the first real
    # query does not pay for it. If the median of the last 20 real reranks stays over the limit
    # for `slow_streak` queries in a row, ATLAS_RERANK is flipped off (until a restart) and a
    # health webhook is sent.
    atlas_rerank_warmup_runs: int = 5
    # The per-query latency budget, in milliseconds per stage (app/retrieval/budget.py).
    # Every breach is measured and logged; only the stages named in BUDGET_ENFORCE act on
    # it ("all", or e.g. "rewrite,rerank"): then the optional stages after it are skipped and
    # the answer is marked degraded. Empty: observe only, answers unchanged. The defaults are
    # the spec's, set for a fast local stack: the free server's planner, search and relevance
    # judge take seconds, so enforce stage by stage once the weekly report shows the numbers.
    budget_rewrite_ms: float = 40
    budget_embed_ms: float = 60
    budget_bm25_ms: float = 30
    budget_vector_ms: float = 80
    budget_fuse_ms: float = 5
    budget_rerank_ms: float = 150
    budget_assemble_ms: float = 20
    budget_first_token_ms: float = 600
    budget_full_answer_ms: float = 3000
    budget_enforce: str = ""
    atlas_rerank_p50_limit_ms: float = 150.0
    atlas_rerank_slow_streak: int = 10
    # Reuse answers to repeated questions for a day (see app/assistant/cache.py).
    assistant_answer_cache: bool = True
    # Deep research for questions that look complex, when the user has not chosen.
    assistant_research_auto: bool = True
    # The judge's and ranker's services, first to last: about 17 small calls a question,
    # so services other than the answers' main ones (Groq, Gemini) go first.
    assistant_judge_services: str = "nvidia,cerebras,sambanova,mistral,github,groq,gemini"
    # Knowledge-base excerpts less similar than this are not shown to the model.
    assistant_min_score: float = 0.3
    assistant_max_tokens: int = 8000

    # Pictures: a gallery from several services at once. Pollinations needs no key
    # ({prompt} and {seed} are filled in); Cloudflare and Hugging Face use their keys
    # above; AI Horde is free but often slow.
    image_url_template: str = (
        "https://image.pollinations.ai/prompt/{prompt}"
        "?width=1024&height=1024&seed={seed}&model=flux&nologo=true"
    )
    image_gallery_size: int = 8
    image_max_wait: float = 90.0
    cloudflare_image_model: str = "@cf/black-forest-labs/flux-1-schnell"
    huggingface_image_model: str = "black-forest-labs/FLUX.1-schnell"
    # Together's free FLUX endpoint, used once TOGETHER_API_KEY is set.
    together_image_model: str = "black-forest-labs/FLUX.1-schnell-Free"
    # Gemini's image model has no free quota: on only for a key with billing.
    gemini_images: bool = False
    gemini_image_model: str = "gemini-2.5-flash-image"

    # When set, adding and removing sources needs `Authorization: Bearer <token>`;
    # searching and asking stay open. Unset, everything is open (local use).
    admin_token: str | None = None
    # With this (a base32 secret for an authenticator app), unlocking admin needs its
    # 6-digit code too, and adding or removing sources needs a signed request.
    admin_totp_secret: str | None = None
    # Answers only from the knowledge base unless a request asks for more (X-Atlas-Open);
    # the public server turns it on (deploy/server/Dockerfile).
    assistant_grounded: bool = False
    # Requests a minute for each API key (X-Atlas-Key).
    api_key_rate_limit_per_minute: int = 60

    # Freshness: days after ingest before a source is STALE (a third of it is FRESH).
    freshness_code_days: int = 30
    freshness_docs_days: int = 90
    freshness_news_days: int = 7

    # Integrations. Webhooks set on the server (comma-separated), beside the admin's own,
    # signed with this secret.
    atlas_webhooks: str | None = None
    atlas_webhook_secret: str | None = None
    # GitHub's push webhook re-indexes a repository source; deliveries are verified with
    # this secret (X-Hub-Signature-256). Unset, /hooks/github answers 404.
    github_webhook_secret: str | None = None
    # MCP servers whose read-only tools the AGENT mode may call: comma-separated
    # name=url pairs (or bare URLs). Results are treated as untrusted retrieved text.
    atlas_mcp_servers: str | None = None
    # Sent to them as `Authorization: Bearer`, if set.
    atlas_mcp_token: str | None = None

    # Requests per client IP per minute; 0 disables. /ask has its own, lower limit
    # because every call is billed.
    rate_limit_per_minute: int = 60
    ask_rate_limit_per_minute: int = 30
    ingest_rate_limit_per_minute: int = 5


settings = Settings()
