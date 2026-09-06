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

## PubPartner — manager AI and individual characters, same or different

PubPartner (`modules/pub_partner_chat.py`) was already wired to this same
registry (that's how it was discovered in the first place) via named
"slots" in `modules/ai_runtime_slots.py`, independently of the Studio
change above. This adds the piece that was missing: making PubPartner's
**manager AI** and each **individual character's AI** independently choose
to share PubCast Studio's brain or run on something else entirely — the
"optionally the same and different" requirement.

### The `same_as_studio` sentinel

Any slot or character profile can be set to the literal string
`"same_as_studio"` instead of a real profile name. When resolved, it
returns whatever AI is *currently* PubCast Studio's primary mind — the
same `PUBCAST_PRIMARY_AI_PROFILE` profile if that's set, or the same
hardcoded local Ollama model Studio falls back to otherwise. This is a
live lookup, not a copy — if Studio's provider changes, anything set to
`same_as_studio` follows automatically.

### Manager AI

Requests with `role: "manager"` (or `pub_manager` / `pubpartner_manager` /
`pub_partner_manager`) resolve through the new `pubpartner_manager` slot in
`ai_runtime_slots.DEFAULT_MODEL_SLOTS`, defaulting to `same_as_studio`.
Override it in `config/ai_runtime.json`'s `profiles`/slot config to give
the manager AI a different brain than Studio.

### Individual characters

Pass `character_id` in the chat request body (e.g.
`{"message": "...", "character_id": "pete"}`) to address one specific
character. Resolution order:

1. `config/ai_runtime.json`'s top-level `"character_profiles"` object —
   `{"pete": "openai_gpt4o_mini", "sir_purfluous": "same_as_studio"}` pins
   Pete to a specific provider while Sir Purfluous explicitly shares
   Studio's.
2. If the character isn't listed there, falls back to the shared
   `pubpartner_character_default` slot — `same_as_studio` by default, so
   every character shares Studio's brain until you pin one.

Verified live: a manager-role request and an unlisted character both
resolved to Studio's current profile; a character explicitly pinned to a
different profile came back with that profile's own model, all through
the real `/api/pub-partner-chat/message` endpoint on the fully booted app.
