# Universal AI provider — swap Studio's brain to any LLM

Studio (the mind that answers most in-app requests — Jeremy, character bots,
choreography decisions) defaults to a hardcoded local Ollama call. This adds
a way to swap that for any provider — cloud or local — via one env var, with
zero change to default behavior when unset.

## How it works

`modules/ai_runtime.py` already defined a config-driven multi-provider
registry (`config/ai_runtime.json`, profiles keyed by name, each pointing at
a `backend`), and `modules/ai_providers.py` already implemented that registry
for `echo`, `ollama`, `openai`, `gemini`, and `local_gguf` — it just wasn't
connected to anything but the separate PubPartner chat feature. This change:

1. Adds `anthropic` (Claude) as a registered backend in `ai_providers.py`.
2. Wires `modules/llm_orchestrator.py`'s Studio path to use that registry
   when `PUBCAST_PRIMARY_AI_PROFILE` names a profile — otherwise Studio
   behaves exactly as before (hardcoded local Ollama, unchanged).

## Using it

1. Edit (or create) `config/ai_runtime.json`. Ready-to-enable profiles are
   already defined by default for `claude_haiku` (Anthropic), `openai_gpt4o_mini`,
   and `gemini_flash` — flip `"enabled": true` and set the matching API key
   env var (`PUBCAST_ANTHROPIC_KEY`, `PUBCAST_OPENAI_KEY`, `PUBCAST_GOOGLE_KEY`).
2. Set `PUBCAST_PRIMARY_AI_PROFILE=claude_haiku` (or whichever profile name)
   before starting the server.
3. That's it — every Studio-role generation (the large majority of the app's
   AI output) now goes through that provider instead of local Ollama.

Any backend added to `ai_providers.PROVIDER_REGISTRY` in the future works
here automatically — no orchestrator changes needed for the next provider.

## What's not (yet) universal

- **Architect** (the planning/GGUF secondary mind) is untouched — still
  local-only (Ollama-wrapped Gemma or a GGUF file). It's a distinct,
  narrower specialization; making it swappable is a separate change if wanted.
- Per-bot providers (`modules/bot_llm_adapter.py`, used for individual AI
  co-host characters like Pete/Sir Purfluous) already supported Anthropic,
  OpenAI, and Gemini independently of this change — that layer was already
  multi-provider, just not the core Studio inference path.
- The universal path folds room history into the prompt as plain text
  (`role: content` lines) rather than a true multi-turn messages array,
  because `ai_providers.GenerateRequest` only carries a single system string
  and a single prompt string. This matches what every existing backend in
  that registry already does (including Ollama's own entry there) — it's an
  existing limitation of the registry, not something this change introduces,
  but it does mean conversational nuance may read slightly differently than
  the hardcoded Ollama Studio path's native `/api/chat` messages array.
