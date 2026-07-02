# NeuroAIon — Agent & Model-Tier Routing

> Run the pipeline on **any** coding agent (Claude Code, OpenAI Codex, Gemini
> Antigravity) or via API, and each task automatically uses the **right model for
> its difficulty** — light for high-volume screening, flagship for the hard,
> correctness-critical work — **without wasting the strong model** on cheap tasks.
> Routing is by *capability tier*, never a pinned version, so a newer flagship
> (e.g. Opus 4.9) is picked up automatically.

## Capability tiers
- **FLAGSHIP** — hardest reasoning / writing / correctness-critical:
  PICO scoping & refinement, data extraction (numbers from tables), evidence
  synthesis + GRADE, manuscript writing, and the self-critique/refinement pass.
- **STANDARD** — judgement over full text, structured work:
  search-strategy (MeSH/Emtree) refinement, screening-conflict adjudication,
  full-text eligibility, risk-of-bias signalling, knowledge-graph claim extraction.
- **LIGHT** — high-volume, simple classification:
  title/abstract screening, deduplication tie-breaks.

## Stage → tier → model (resolved dynamically)
| Stage | Tier | Claude | Openai | Gemini | Deepseek |
|---|---|---|---|---|---|
| scoping | flagship | claude-opus-4-8 | gpt-5.1 | gemini-3-pro | deepseek-chat |
| protocol | flagship | claude-opus-4-8 | gpt-5.1 | gemini-3-pro | deepseek-chat |
| search_strategy | standard | claude-sonnet-5 | gpt-5.1-mini | gemini-3-flash | deepseek-chat |
| dedup | light | claude-haiku-4-5 | gpt-5.1-nano | gemini-3-flash-lite | deepseek-chat |
| screen_ta | light | claude-haiku-4-5 | gpt-5.1-nano | gemini-3-flash-lite | deepseek-chat |
| adjudication | standard | claude-sonnet-5 | gpt-5.1-mini | gemini-3-flash | deepseek-chat |
| eligibility | standard | claude-sonnet-5 | gpt-5.1-mini | gemini-3-flash | deepseek-chat |
| extraction | flagship | claude-opus-4-8 | gpt-5.1 | gemini-3-pro | deepseek-chat |
| rob | standard | claude-sonnet-5 | gpt-5.1-mini | gemini-3-flash | deepseek-chat |
| synthesis | flagship | claude-opus-4-8 | gpt-5.1 | gemini-3-pro | deepseek-chat |
| claims | standard | claude-sonnet-5 | gpt-5.1-mini | gemini-3-flash | deepseek-chat |
| reporter | flagship | claude-opus-4-8 | gpt-5.1 | gemini-3-pro | deepseek-chat |
| critic | flagship | claude-opus-4-8 | gpt-5.1 | gemini-3-pro | deepseek-chat |

*The model columns are today's defaults; they **auto-upgrade** (see below).*

## How each agent should run it
When the pipeline runs in **cowork mode** (no API key — the controlling agent is
the provider), every LLM call arrives tagged with a `tier`. Map it to **your**
model of that class:

- **Claude Code** → FLAGSHIP = your top Opus (today Opus 4.8; if Opus 4.9/5 ships,
  use that), STANDARD = current Sonnet, LIGHT = current Haiku.
- **OpenAI Codex** → FLAGSHIP = your top GPT-5/o-series reasoning model,
  STANDARD = the GPT-5 *mini* class, LIGHT = the *nano*/4.1-mini class.
- **Gemini Antigravity** → FLAGSHIP = latest Gemini **Pro**, STANDARD = Gemini
  **Flash**, LIGHT = Gemini **Flash-Lite**.

Rule of thumb: **always use your *latest* model in the requested tier** — never a
specific older version. That is what keeps quality maxed while never burning the
flagship on a screening call.

## Dynamic upgrade & overrides (precedence)
1. **Per-family env** — `NEUROAION_CLAUDE_FLAGSHIP`, `NEUROAION_OPENAI_STANDARD`, `NEUROAION_GEMINI_LIGHT`, …
2. **Global-tier env** — `NEUROAION_MODEL_FLAGSHIP` / `_STANDARD` / `_LIGHT`.
3. **Latest-by-pattern** — if a live model list is available, the newest id matching the tier pattern (e.g. `claude-opus-*`) wins → Opus 4.9 auto-selected over 4.8.
4. **Default** — the current-best fallback in `routing.FAMILY_MODELS`.

## API mode
Set `NEUROAION_PROVIDER=anthropic|openai|deepseek` (+ key). `llm.provider_for_tier(tier)`
resolves the concrete model per the precedence above and builds the provider, so
extraction/synthesis/writing get the flagship and screening gets the light model
automatically. A dedicated high-throughput screening backend can still be pinned
with `--screen-provider` / `--screen-model`.

`docs/routing.json` is the machine-readable version (regenerate with
`python -c "import json,neuroaion.routing as r; print(json.dumps(r.routing_json(),indent=2))"`).
