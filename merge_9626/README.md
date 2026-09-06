# merge_9626

This directory is the merge batch from session 9626 — uploaded files staged
here as-is, unmodified, for review before anything replaces the live
`main.py` / `modules/` tree.

Nothing outside `merge_9626/` was touched by this commit. This is staging,
not integration.

## Layout

- `root/` — files meant for the repo root once merged:
  - `main.py` — a newer main.py (4,393 lines) that already has clip upload,
    take manager, media router/intake, and PEQ routes mounted (unlike the
    3,902-line main.py currently pushed on this branch under `extracted/`,
    which has none of those mounts).
  - `PubWorld.jsx`
  - `SESSION_SUMMARY_20260905.md`
  - `COMPLETE_HANDOFF_20260905.md`
  - `MOUNT_INSTRUCTIONS_IMMEDIATE.md`
- `modules/` — files meant for `modules/`:
  - `studio_camera_preflight.py`, `pubcast_vision_routes.py`,
    `virtual_camera_bus.py`, `pubcast_vision_integration.py`,
    `camera_engine_bridge.py`, `capture_routes.py`, `capture.py`,
    `skeleton_tracker.py`, `bubble_stack.py`, `bubble_routes.py`,
    `peq_integration.py`, `peq_broker.py`, `media_intake_routes.py`,
    `media_intake.py`, `media_router.py`, `pubcast_take_manager.py`,
    `pubcast_clip_upload_route.py`
- `cre_eq_for_repo_root/` — unzipped as-is; filename says destination is repo root.
- `peq_for_modules_dir/` — unzipped as-is; filename says destination is `modules/`.
- `theater_render_pipeline/` — unzipped as-is; destination not yet confirmed.

## Known duplicates in this batch

Several files were uploaded twice across two batches with identical or
near-identical content (`studio_camera_preflight.py`, `pubcast_vision_routes.py`,
`peq_broker.py`). The newest upload of each was kept here.

## Not included

Four audio files (`Uploaded_File_x_Uke_song_Mashup*.mp3/.m4a`) were part of
the same upload batch but are not code and were not staged here pending
confirmation they belong in this repo.
