# Extracted files

These are un-zipped, unmodified copies pulled out of the repo's own zip archives, so they can be
fetched as plain files/URLs (no zip extraction, no special GitHub tooling needed).

- `main.py` — from `pub 8-30-26 710.zip` (the most recently added bundle, 2026-08-31).
- `modules/choreography_controller.py`, `modules/choreography_runtime.py` — from
  `pubcast_run_bundle (2).zip` / `PubCast_AI_REPAIRED_2026-08-24.zip` (2026-08-23 content, last
  repackaged 2026-08-27). The 08-31 zip shipped `main.py` alone without a `modules/` folder, so
  these are the most recent copies of those two files that actually exist in the repo.

Confirmed by direct search of every zip in the repo: `modules/pubcast_take_manager.py`,
`modules/pubcast_clip_upload_route.py`, and `modules/media_router.py` do not exist anywhere in
this repo. `modules/media_intake_routes.py` exists in the same bundles as the choreography files
above but is not imported by `main.py`.
