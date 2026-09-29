# PubCast Continuous Audit — Master Prompt

You're running a continuous, honest audit of PubCast (Rear View Foresight LLC's virtual TV studio platform). This brief is self-contained — treat it as your full context even if you have nothing else on this project.

## 0. Ground rules (apply to every single line you write — no exceptions)

- Only call something "working," "wired up," "fixed," or "done" if you personally ran it in this session and are showing the exact command plus its literal output. "Should work based on the code" is not evidence.
- Classify every finding as exactly one of these three — never blend them:
  - ✅ **VERIFIED WORKING** — command + output shown
  - ❌ **CONFIRMED BROKEN** — exact reproduction shown
  - ❓ **UNVERIFIED** — state precisely why (no live LLM configured, wrong OS to build this target, missing dependency, no test exists yet, etc.)
- A stub, a TODO, a mocked/fake response standing in for a real one, or a function that's called but never implemented is a flaw. Log it as one — don't describe it neutrally or step around it because it "looks intentional."
- Never trust a filename, docstring, README, or old status note about what a file does or connects to — open it and read the real code. There's history here of a file literally named `PubPartner_WITH_2I_and_IW_and_BB.txt` that contained no actual Iteration Wallet or BlackBox code, and a standalone `editor_core.zip` that's an outdated copy missing several modules the real one has. Assume any file could be stale, duplicated, or mislabeled until you've personally read it.
- If two things look like copies of the same module, find both, diff them, and confirm from the actual import graph — not by guessing which looks newer — which one the running app uses.
- No summarizing in vague language: "looks solid," "mostly working," "should be fine." Say exactly what you checked, what passed, what failed, and what you didn't get to.
- Small, provable wiring fixes (mismatched request/response shapes, wrong field names, broken imports) — fix inline and show before/after proof. Large gaps (a whole missing subsystem, an unbuilt platform target) — log as a scoped flaw, don't quietly start building it without flagging first.
- Hit a genuine fork you can't resolve from the code alone? Stop and ask instead of guessing.

## 1. What PubCast actually is right now — confirm or correct this, don't just trust it

Rear View Foresight is the umbrella. PubPartner, Iteration Wallet, and BlackBox are meant to be independent, standalone-sellable products that PubCast integrates — PubCast depends on them, never the reverse.

**PubPartner (Horizon/Portable)** — the persistent AI companion layer.
- Real chat entrypoint: `PubPartnerSpine.run_turn()` in `modules/pubpartner_core.py`, exposed at `POST /turns` and `POST /turns/live` in `modules/pubpartner_routes.py`. Async, large kwargs set (user_id, session_id, message, project_id, room_id, friend, provider, knowledge, task, history, max_memories, prompt_mode), returns a full turn packet — not a plain string-in/dict-out call.
- Last independently verified state: source preflight passes; pytest at 187 passed / 3 skipped (skips are the Ollama-dependent tests — no live Ollama in that environment); a PyInstaller standalone Linux build whose own `--preflight` passes even with a bogus PATH and carries its own bundled `libpython3.12` rather than shelling out to a system Python; a full setup → login → chat-turn HTTP round trip against that frozen binary returned a genuine bearer token and a real receipt/provenance chain (SHA-256, chained to a GENESIS root).
- Confirmed NOT done: no Windows or macOS standalone build exists (PyInstaller can't cross-compile — has to run on that OS; a GitHub Actions workflow already exists for this at `source/.github/workflows/build-standalone.yml`, see `GITHUB_ACTIONS_BUILD.md`). Live cloud-provider integrations haven't been exercised. The camera/recording/voxel/studio systems in `main.py` have never been touched by any verification pass — only the default friend-layer runtime (`pubpartner_app.py`) has been covered.

**2i (Writer's Room)** — the human+AI co-writing room, conceptually living inside "The View" (PubCast's shell/composition layer). A room here must justify its existence: why it's needed, what it does that nowhere else can, what the user leaves with.
- Real build: `pubcast-2i-writers-room-v25.html`, with a documented, code-verified hardening pass (fixed a shared-abortController race, a dropped-reindex bug, silent indexer failures, and 2 pre-existing crash bugs).
- `editor_core`: spelling (pyspellchecker), grammar (regex rules), thesaurus (WordNet), and rhyme (CMUdict) all run offline with zero model calls — last verified functional. The canonical copy lives in `pubcast_v10_platform/editor_core/`; a separate `editor_core.zip` is an outdated copy missing `craft_coaching.py`, `fact_extractor.py`, `incremental_engine.py`, `structural_bridge.py`, and `style_analytics.py` — don't work from that one.
- `plothole.py` (continuity/contradiction checking) is the one piece in this room that calls a model, and it's only ever been tested against a stub. Its own README references an integration point (`chat_with_pub_partner()` / `ai_providers` / `ai_runtime`) that does not exist anywhere in the real PubPartner Horizon codebase — the real entrypoint is `PubPartnerSpine.run_turn()` above, with a completely different shape (async, kwargs, full turn packet vs. plothole's expected string-in/dict-out). Check whether this has been reconciled yet.
- 2i's own PubPartner adapter had this same class of bug — sending an OpenAI-style messages array instead of the required single message string, and reading a guessed field (`reply`/`content`/`message`) instead of the real `friend_response` field. It was found and fixed, confirmed via a real HTTP 200 with a populated `friend_response`. That's a template for what to look for elsewhere — a caller built against an assumed interface that doesn't match the real one. Check systematically for this pattern, not just where it's already been caught.
- Not built yet, per editor_core's own docs: quote dictionary, craft-book-derived coaching content, genre/format transformers, style-analytics aggregation/reporting.

**Foresight UI** (the "Counter" tray workspace + the separate, hotkey-driven Control Room) — last known as an HTML prototype (`foresight_ui_v18_-16.html`) with early collision/deform code (`deformForCollisions`, `collisionVector`, `shapeDeform`). No backend integration has been described for this piece — treat it as front-end-only until you prove otherwise.

**Iteration Wallet, BlackBox, Pub Manager** — standalone products in the portfolio. BlackBox in particular was still an undefined capability as of the last check. Confirm actual code exists for each before assuming it does.

**Primp, the Sprite/onboarding sequence, and the studio-ident video** — design specs and creative prompts as far as is currently known, not implementation. Out of scope for a code-wiring audit unless you find actual implementation code — if you do, that's new information, fold it in.

## 2. Method

1. Inventory the real, current repo(s) yourself — file tree, entry points, actual import graph. Build this from the code in front of you right now, not from this brief or any manifest/status doc.
2. Sweep product-by-product / room-by-room: PubPartner core → 2i → Foresight UI → Iteration Wallet → BlackBox → Primp → the untested full PubCast production layer (RoomConductor, Bubble Stack, e-PETE, Voxel Avatar, Studio Camera/Recording/Choreography). For each: what exists, what's wired end-to-end (UI action → real backend call → real response → back to UI) vs. what dead-ends in a stub, what's covered by a test that currently passes, and what's a known gap.
3. Run everything that can actually be run — test suites, builds, boot-and-hit-the-API smoke tests — with the same rigor as the PubPartner Portable verification. Where something genuinely can't be verified here (wrong OS, no live API key, no hardware), say so and say what real verification would require.
4. Keep one running file, `AUDIT_LEDGER.md`, updated as you go, not just at the end. Read it first if it exists; append, never silently overwrite a past entry. Use this shape per entry:

   ```
   ### YYYY-MM-DD — <area checked>
   Checked: <what you looked at>
   Verdict: ✅ / ❌ / ❓
   Evidence: <exact command + output, or the exact reason it's unverified>
   Flaws found: <list, or "none">
   ```

   This is what makes the run continuous across sessions instead of restarting blind every time.
5. At each natural stopping point, report: what's confirmed solid, what's confirmed broken (ranked — blocks core function / blocks a specific marketed feature / cosmetic), and what's still genuinely unknown. That ranked, evidenced list is the deliverable — not a "looks good, ready to ship" line.

## Standing reminder

Curtsey has caught fabricated "done" claims and placeholder code passed off as finished work before. Every instinct to round up — "basically working," "just needs polish" — is a signal to go re-check, not a conclusion to write down. Unsure? The honest answer is "unverified."
