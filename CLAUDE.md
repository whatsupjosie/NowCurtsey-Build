# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This repository currently contains a single archive, `PubCast_AI_REPAIRED_2026-08-24.zip`, which holds the full "PubCast AI" application source (a FastAPI backend plus Rust rendering components). There is no unpacked source tree committed to git — extract the zip locally to work with the code:

```
unzip PubCast_AI_REPAIRED_2026-08-24.zip -d extracted
```

The archive's root directory is `run_bundle/`. Everything below refers to paths inside `run_bundle/` once extracted. Do not commit an unpacked copy back into the repo unless the user explicitly asks for it — the zip is the tracked artifact.

## What's canonical vs. draft/handoff material

This bundle is the output of many iterative AI development "runs," so it mixes live application code with drafts, patches, and dev logs. Before editing, confirm which copy of a file is actually wired in:

- **`modules/`** is the live, canonical application (169 Python files). `main.py` at the bundle root is a thin wrapper (`app = modules.main.app`, forwards attributes live) — the real FastAPI app and boot logic live in `modules/main.py`.
- **`main_UPDATED.py`** (bundle root, ~165KB) is a newer/larger draft of the boot file, NOT imported by anything — `main.py` imports `modules.main`, not `main_UPDATED.py`. Treat it as reference/merge-candidate only, not live code.
- Suffix conventions to watch for: `_FIXED` (a corrected version meant to supersede the unsuffixed original — check both exist and diff before trusting either), `_raw` (earlier/unwrapped predecessor of a hardened version, e.g. `avatar_system_raw.py` vs `avatar.py`, `bridge_raw.py` vs `bridge_bulletproof.py`), `_CORRECTED` (e.g. `requirements_CORRECTED.txt` — the canonical requirements file; there is no plain `requirements.txt`).
- **`run2_rust/`**, **`run3_bridge/`**, **`run5_pubworld_camera/`**, **`run5_patches/`**, **`run6_bubble_stack/`** are per-run snapshots/drafts from earlier development iterations (Rust renderer source, PubWorld voxel prototype, patch files, Bubble Stack dossiers). Their live equivalents, where they exist, are in `modules/` (e.g. `modules/bubble_stack.py`, `modules/bridge_bulletproof.py`).
- **`pubcast_camera_recovery/`** and **`pubpartner_verified/`** are standalone, self-contained sub-projects (each with their own `Cargo.toml`/tests) not imported by `modules/main.py`.
- **`handoffs/`** and the root-level `RUN*_HANDOFF*.md` / `SESSION_HANDOFF_*.md` files are historical dev-session logs, duplicated in both locations. They're useful for understanding *why* something was built a certain way but are not living documentation — no need to read them routinely. The most recent, currently-relevant status docs are `FIXES_APPLIED_2026-08-24.md` and `BUGFIX_RUN_HANDOFF_2026-08-24.md` at the bundle root.

## Running the app

```
python main.py
# or
uvicorn main:app --host 0.0.0.0 --port 8000
```

Configuration is entirely via environment variables read by `modules/appconfig.py` (`Settings`): server host/port/debug (`PUBCAST_HOST`, `PUBCAST_PORT`, `PUBCAST_DEBUG`), storage dirs (`PUBCAST_DATA_DIR`, `ASSETS_DIR`, `STATIC_DIR`), local model names (`STUDIO_MODEL`, `ARCHITECT_MODEL`), TTS host/port (`PUBCAST_LARYNX_*`), AI provider keys, and recording limits. `PUBCAST_JWT_SECRET` and `PUBCAST_OWNER_PASSWORD` must be set for anything beyond local dev.

Install dependencies from `requirements_CORRECTED.txt`. Core: `fastapi`, `uvicorn[standard]`, `starlette`, `pydantic`, `httpx`, `jinja2`, `python-multipart`, `aiosqlite`, `numpy`, `websockets`, `python-jose[cryptography]`, `passlib[bcrypt]`. `posix_ipc` (used by the Rust SHM bridge) is POSIX-only and guarded with `sys_platform != "win32"` — on Windows the bridge falls back to a filesystem transport. Cloud LLM providers (`openai`, `google-generativeai`, `anthropic`) are optional/commented out.

## Tests

Run with `pytest` from the bundle root (no `pytest.ini`/`pyproject.toml` — plain pytest discovery). `conftest.py` at the root provides two fixtures:
- `client_no_lifespan` — imports `main`/`TestClient` without running the FastAPI lifespan, for structural/import-level tests.
- `client` — session-scoped, runs the full lifespan (boots Hub, BYOK, Cricket, Purfluous, Studio Control, etc.) for integration tests.

It also puts `ROOT`, `ROOT/modules/wired`, `ROOT/pubpartner_verified`, and `ROOT/modules` onto `sys.path`. A `conftest_FIXED.py` also exists at the root — `conftest.py` (unsuffixed) is what pytest actually discovers by default, so treat it as canonical unless you've confirmed otherwise. Other test files: `modules/wired/test_hardening.py`, `test_run1_live.py`, `test_04_websockets_FIXED.py`, `pubpartner_verified/tests/`, `run3_bridge/test_pubcast_twin_engine_service.py`.

As of the latest bundle snapshot (`BUGFIX_RUN_HANDOFF_2026-08-24.md`), the suite is at 575 passing / 6 known-failing (up from 556/25 after a bugfix pass covering a path-traversal issue in `ai_runtime.py`, an auth bypass in `route_security.py`, duplicate routes, and other fixes — see that file for the full list before assuming a failure is new).

Known environment gaps noted in `FIXES_APPLIED_2026-08-24.md`: DeepFace/MediaPipe absent (facial analysis is simulated), the Rust renderer isn't running in sandboxed environments (bridge falls back to filesystem/SHM emergency path — `bridge_connected=false, bridge_operational=true`), `sounddevice` absent.

## Architecture: boot sequence

`modules/main.py` boots subsystems in dependency order inside a FastAPI `lifespan` context manager, documented in its own docstring as a 12-step sequence. Most steps past #1 are wrapped in `try/except ImportError` with a `_HAS_*` flag, so the server still boots if an optional subsystem's dependencies are missing:

1. `Hub` (`modules/hub.py`) — WebSocket message router + room/production-state persistence.
2. `RoomManager` (`modules/rooms.py`); 2b–2d. `PerformanceManager`, `ChoreographyController`, `LightingEngine` (optional).
3. `InferenceManager` (`modules/inference.py`) — coordinates local dual-model inference ("Ollama Studio" + "GGUF Architect") via `llm_orchestrator.py`.
4. `CricketKeeper` — per-character SQLite memory (optional).
5. `BotManager` (`modules/bots.py`) — AI co-hosts Pete, Sir Purfluous, Jeremy Cricket.
6. `CameraManager` + `RecordingService` (`modules/cameras.py`, `modules/recording.py`).
7. `GovernanceEngine` (`modules/governance.py`) — bans, mute, consent, waiting room.
8. `BYOKManager` (optional) — user-supplied API keys.
9. `ThinkingContext` (optional) — Jeremy conductor.
10. `EtherealAvatarManager` (optional) — "57-joint neon avatars."
11. **EVO Protocol** (optional, `modules/evo.py`) — "Switchblade + VDI + E-Pete Sacred Chain," a higher-level orchestration layer over inference/character systems.
12/12b. `PubCastVault` (OS-level file protection) and a `Doctor` environment verifier (both optional).

## Architecture: major subsystems in `modules/`

- **Core runtime/routing**: `hub.py` (message router), `rooms.py` (Room/Participant/RoomManager), `models.py` (Pydantic models), `route_security.py` (auth enforcement).
- **Bots/LLM**: `bots.py` (BotManager), `inference.py`, `llm_orchestrator.py`/`llm_framework.py` (multi-provider dispatch), `ai_providers.py`/`ollama_provider.py`.
- **Avatar/animation**: `avatar.py`, `avatar_motion.py`, `avatar_performer.py` (WebSocket bridge to the Rust renderer), `avatar_skeleton_system.py`, `ethereal_avatars.py`, `animation_authority.py`, `choreography_controller.py`/`choreography_runtime.py`.
- **Governance/safety**: `governance.py`, `governance_routes.py`, `governance_waiting_room.py`, `dressing_room_security.py`.
- **Cameras/recording**: `cameras.py`, `cameras_advanced.py`, `camera_boxer.py`, `recording.py`, `recording_pipeline.py`, `capture.py`.
- **Bubble Stack**: `bubble_stack.py`, `bubble_routes.py`, `bubble_jeremy_adapter.py`.
- **Alex (companion AI)**: `alex_core.py`, `alex_jeremy_bridge.py`, `alex_memory.py`, `alex_routes.py`.
- **Affect/context**: `affect_context_engine.py`, `affect_choreo_bridge.py`, `affect_wiring.py`, `contradiction_engine.py`, `theory_graph.py`.
- **BYOK**: `byok_manager.py`, `byok_routes.py`, `credentials.py`.
- **Voxel/PubWorld**: `pubworld.py`, `pubworld_blocks.py`, `pubworld_hotspots.py`, `voxel_asset_manager.py`, `voxel_block_kit.py`.
- **Python↔Rust bridge**: `bridge_bulletproof.py`/`unified_bridge.py` — POSIX shared-memory transport (via `posix_ipc`) to the Rust renderer, with a filesystem-based emergency fallback ("Path C") when SHM or the Rust process is unavailable.
- **Memory**: `memory_engine.py`, `memory_ingestor.py`, `universal_memory_system.py`, `cc_memory_store.py`, `personal_ai_memory_api.py`.
- **Vault/security**: `pubcast_vault.py`, `vault_engine.py`/`vault_engine_hardened.py`, `secure_secrets.py`, `key_recovery.py`.
- **Auth/users**: `auth.py`, `auth_routes.py`, `userdb.py`.

## Rust components

There is no single unified Rust crate — three separate trees exist:
- `run3_bridge/` — has a real `Cargo.toml`; its Python bridge files are near-duplicates of the ones now canonical in `modules/`.
- `run2_rust/` — loose `.rs`/`.wgsl` source files with no `Cargo.toml`; not currently buildable, treat as draft reference.
- `pubcast_camera_recovery/` — its own standalone Cargo project (`Cargo.toml` + `Cargo.lock`, `src/camera`, `src/scene`, `src/voxel`), a separate rebuild/recovery attempt of the renderer.

When wiring Python to Rust, work through `modules/bridge_bulletproof.py` and `modules/avatar_performer.py`, not the files under `run2_rust/`/`run3_bridge/` directly.
