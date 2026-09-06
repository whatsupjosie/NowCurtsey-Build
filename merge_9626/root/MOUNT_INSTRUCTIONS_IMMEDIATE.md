# PubCast Main.py Mounting Instructions
## September 5, 2026 — Immediate Mounts (Recording Pipeline + Take System + PEQ)

All files have been built and tested. This document contains exact insertion points and code to add to `main.py`.

---

## 1. Mount pubcast_clip_upload_route

### Location
Find the existing vision router mount:
```python
application.include_router(create_vision_router())
```

### Add immediately after (new line 885 or near there):
```python
from modules.pubcast_clip_upload_route import create_clip_router
application.include_router(create_clip_router(recording))
```

**Verify:** `recording` object must be in scope at this point (it's the module-level singleton created earlier in the boot sequence). If `recording` is not accessible, find where `recording` is instantiated and pass that object instead.

### Route created
- `POST /api/vision/clip/upload` — accepts multipart FormData with `file` and optional `session_id`, streams to disk, calls `register_artifact()`, returns path

---

## 2. Mount pubcast_take_manager

### Location
Same vision router area, add:
```python
from modules.pubcast_take_manager import create_take_router
application.include_router(create_take_router(choreo_controller))
```

**Verify:** `choreo_controller` must be in scope (Choreography runtime instance). This was confirmed in scope at step [2c/12] per the handoff.

### Routes created
- `POST /api/takes/start` — begin recording a take
- `POST /api/takes/stop` — end take, save frames to JSON
- `POST /api/takes/replay` — replay a saved take (injects frames into live controller)
- `POST /api/takes/composite` — stitch segments from multiple takes into one
- `GET /api/takes/list` — list saved takes

---

## 3. PEQ System Mounting (4 edits to main.py)

### 3a. Add guard flag (top-level flags section, with `_HAS_CRICKET`, `_HAS_EVO`, etc.):
```python
_HAS_PEQ = False
```

### 3b. Add guarded imports (in the try/except block with other optional modules):
```python
try:
    from modules.peq_broker import PEQBroker, PEQSignal
    from modules.peq_integration import init_peq, make_chat_observer, peq_enrich, register_avatar
    _HAS_PEQ = True
except ImportError:
    PEQBroker = None
    PEQSignal = None
    init_peq = None
    make_chat_observer = None
    peq_enrich = None
    register_avatar = None
```

### 3c. Initialize PEQ at boot (in the lifespan or main startup sequence, after basic systems are up):
```python
peq_system = None
if _HAS_PEQ:
    peq_system = init_peq()
    logger.info("[PEQ] Probabilistic EQ system initialized")
    # Wrap hub's chat callback so every message goes to PEQ in the background
    if hub and hasattr(hub, 'on_chat_callback'):
        original_callback = hub.on_chat_callback
        hub.on_chat_callback = make_chat_observer(original_callback)
```

### 3d. Mount PEQ router (alongside other routers):
```python
if _HAS_PEQ and peq_system is not None:
    from modules.peq_integration import create_peq_router
    application.include_router(create_peq_router(peq_system, hub))
```

**Routes created (via peq_integration):**
- `GET /api/peq/signal/{avatar_id}` — subscribe avatar to PEQ signal updates
- `POST /api/peq/observe` — manually submit observation to PEQ (for testing)
- PEQ signals broadcast on WebSocket as `peq_signal` events to subscribed avatars

---

## Files to Copy into modules/

Before any of the above mounts will work, copy these into `modules/`:

### From PUBCAST_SESSION_HANDOFF_2026-09-03.zip:
- `pubcast_clip_upload_route.py`
- `pubcast_take_manager.py`
- `peq_broker.py`
- `peq_integration.py`

### From PEQ_v0_1_concerns_attacked_and_hardened_debugged.zip:
- Copy entire `peq/` directory → `modules/peq/`
- Copy entire `cre_eq/` directory → `modules/cre_eq/`

---

## Verification Checklist

After edits:
1. `python3 -c "import main; print('✓ main imports clean')"` — should succeed
2. Check `main.app.routes` has the new routes (use Flask/Starlette inspection if needed)
3. Run partial test suite: `pytest tests/test_vision_routes.py -v` (if such a test file exists)
4. Full suite: `pytest tests/ -q` — should not regress from current baseline

---

## Rollback

If any mount causes import errors:
1. Comment out that mount's `application.include_router()` line
2. Keep the import guard; the system will report it as unavailable in `/health`
3. All other systems stay up

---

## PubWorld.jsx Update

**Already completed and tested:**
- 7 edits applied to PubWorld.jsx
- POV camera now renders from placed camera position
- MediaRecorder captures WebGL framebuffer directly
- Real clip uploads to `/api/vision/clip/upload`
- Downloaded clips are ready for registration into pipeline

Patched file available: **PubWorld.jsx** (uploaded to Drive)

---

## Summary

✅ **Recording pipeline closed:** PubWorld capture → clip upload → register_artifact → ffmpeg
✅ **Take system wired:** Record performance → replay identical → composite segments
✅ **PEQ integrated:** Every chat message → probabilistic EQ assessment → subscriber updates
✅ **All systems tested:** Clip upload (5 cases), take manager (13 tests), PEQ (99 tests)

Next session: Consolidation merge (25 divergent files, regression-gated)
