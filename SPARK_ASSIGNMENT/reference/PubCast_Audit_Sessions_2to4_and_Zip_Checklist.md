# PubCast Audit — Sessions 2, 3 & 4 + Zip Checklist

Each block below is a self-contained follow-up to the master prompt (`PubCast_Continuous_Audit_Prompt.md`). Paste one per session.

## How these fit together

- Session 1 = the master prompt (ground rules + system map + method).
- Sessions 2-4 below assume those same ground rules apply. If you're starting a brand-new chat with no memory of the master prompt, paste the master prompt first, then the relevant session block below.
- Every session should read `AUDIT_LEDGER.md` first (if it exists yet) before touching anything else, and update it before stopping.

---

## Session 2 — PubPartner core, build targets, and the untested runtime layer

Continue the PubCast continuous audit under the same ground rules as the master prompt (no claiming "done"/"working" without a shown command + output; ✅/❌/❓ only; stubs and placeholders are flaws; never trust a filename/docstring/README over the real code). Read `AUDIT_LEDGER.md` first if it exists.

This session's focus is PubPartner Horizon/Portable and the parts of it that were previously untouched or unfinished:

1. Re-verify what was already checked before — on the *current* code, don't assume last time's result still holds: source preflight, the pytest suite (last known: 187 passed / 3 skipped, skips = Ollama-dependent), and a live setup → login → chat-turn HTTP round trip against `PubPartnerSpine.run_turn()` via `POST /turns`.
2. Windows and macOS standalone builds don't exist yet (PyInstaller can't cross-compile). Check whether `source/.github/workflows/build-standalone.yml` can actually run from here to produce them; if it can, run it and verify the output the same way the Linux build was verified (its own `--preflight`, a real HTTP round trip). If it can't run in this environment, say exactly why and what would be needed.
3. Check whatever live cloud-provider integrations exist in the provider layer. If you have credentials to test with, test them for real. If not, mark unverified and say what a real test would need.
4. Start mapping the parts of `main.py` that have never been touched by any verification pass: the camera, recording, voxel avatar, and studio choreography systems. You're not expected to fully verify all of it in one session — just establish, honestly, what exists, what's called from where, and what's a stub, so the next session doesn't start from zero.

Update `AUDIT_LEDGER.md` with everything above before you stop.

---

## Session 3 — 2i Writer's Room, editor_core, and the plothole.py interface mismatch

Continue the audit under the same ground rules. Read `AUDIT_LEDGER.md` first.

This session's focus is the 2i Writer's Room and its editor_core:

1. Confirm `pubcast-2i-writers-room-v25.html` still behaves as `HARDENING_NOTES.md` claims — actually exercise the shared-abortController path, the reindex path, and the indexer. Don't just re-read the notes and assume they still hold.
2. Confirm the canonical `editor_core` being imported at runtime is the one at `pubcast_v10_platform/editor_core/`, not the outdated standalone `editor_core.zip` copy (missing `craft_coaching.py`, `fact_extractor.py`, `incremental_engine.py`, `structural_bridge.py`, `style_analytics.py`).
3. `plothole.py` currently expects an interface (`chat_with_pub_partner()` / `ai_providers` / `ai_runtime`) that doesn't exist in the real PubPartner Horizon codebase. The real entrypoint is `PubPartnerSpine.run_turn()` — async, kwargs, full turn packet, a completely different shape. Either wire `plothole.py` to the real entrypoint and prove it end-to-end with an actual continuity check on real content, or document precisely why that can't be done this session and what's blocking it.
4. 2i's PubPartner adapter had this same class of bug (wrong request shape, wrong response field) and was already fixed once. Check the rest of 2i's PubPartner-facing code for the same pattern — don't assume that fix was the only instance of it.
5. Confirm the not-yet-built list is still accurate: quote dictionary, craft-book-derived coaching content, genre/format transformers, style-analytics aggregation/reporting. Note anything that's since changed.

Update `AUDIT_LEDGER.md` before you stop.

---

## Session 4 — Foresight UI wiring, unconfirmed products, and the consolidated flaw list

Continue the audit under the same ground rules. Read `AUDIT_LEDGER.md` first.

This session's focus is the UI layer, the still-unconfirmed products, and pulling everything together:

1. Determine, for real, whether the current Foresight UI (the "Counter" tray workspace — `foresight_ui_v18_-16.html` or whatever's since replaced it) is wired to any backend at all, or is purely client-side. Trace any fetch/API calls it makes; if there are none, say so plainly rather than calling it "not yet confirmed."
2. For Iteration Wallet, BlackBox, and Pub Manager: confirm whether real implementation code exists at all. If it does, confirm whether it's actually wired into PubCast/PubPartner or sitting orphaned. BlackBox specifically was last known as an undefined capability — check if that's changed.
3. For Primp: confirm whether any of the described infrastructure (the crop/zone tooling, the priming → fill → powder pipeline, etc.) exists in code, or whether it's still spec-only.
4. Pull sessions 1–4 together into one consolidated, ranked flaw list: blocks core function / blocks a specific marketed feature / cosmetic-only / not yet built at all. This is the actual "definitive flaw list" deliverable — every line needs to trace back to a specific `AUDIT_LEDGER.md` entry with real evidence, not a fresh impression.

Update `AUDIT_LEDGER.md` and present the consolidated list as the final output of this pass.

---

## What to zip

Don't hand-pick individual files — zip whole project roots with folder structure intact. Cherry-picked files break because Python imports (and the HTML builds' relative references) need the real tree around them. If it's too large for one upload, split by product root below into separate zips rather than flattening folders together.

Confirmed-relevant roots, based on what's actually been discussed:

- **PubPartner Horizon/Portable** — the current `source/` tree, plus the `standalone_linux_x86_64/` folder if you want the existing build checked (not just rebuilt from source). Confirm these are inside it: `modules/pubpartner_core.py`, `modules/pubpartner_routes.py`, `pubpartner_app.py`, `main.py`, `source/.github/workflows/build-standalone.yml`, and the doc files (`GITHUB_ACTIONS_BUILD.md`, `START_HERE_PORTABILITY.md`, `KNOWN_LIMITATIONS.md`, `WINDOWS_LAUNCH_VERIFICATION.md`) so findings can be checked against documented history.
- **PubCast core / pubcast_v10_platform** — where 2i and the story/room machinery live: `editor_core/` (the canonical one, not any standalone `editor_core.zip`), `pubcast-2i-writers-room-v25.html`, `HARDENING_NOTES.md`, `plothole.py`, `pubcast_story_bible.py`, `story_routes.py`, `projects.py`, `timeline.py`, `timeline_routes.py`, `bubble_stack.py`, `room_conductor.py`, `pubcast_room_layout.py`, plus wherever the camera/recording/voxel/studio code (e-PETE, Voxel Avatar, Studio Camera/Recording/Choreography) actually lives.
- **Foresight UI** — the current tray/Counter workspace build (`foresight_ui_v18_-16.html` or its successor).
- **Iteration Wallet, BlackBox, Pub Manager** — whatever code roots exist for these, even partial/experimental ones. If you're not sure something counts, include it — the audit needs to see it to tell you whether it's real.
- **Primp** — whatever code exists for it, if any.

Not needed for this pass: the Sprite/onboarding design docs, the studio-ident video prompt, and anything that's pure creative-writing spec with no implementation — those aren't code-audit material until there's actual code behind them.
