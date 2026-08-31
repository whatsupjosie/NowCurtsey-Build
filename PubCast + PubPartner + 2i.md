# PubCast + PubPartner + 2i
# Integrated System Architecture & Execution Plan

**Status:** Architecture reconciled and execution plan normalized  
**Purpose:** Establish one coherent implementation plan for integrating PubCast, PubPartner, 2i, and Foresight without losing the existing subsystem boundaries or graceful-fallback philosophy.

---

## 1. Executive Summary

The system consists of three currently identifiable application layers plus the Foresight UI layer:

1. **PubCast AI** — the broadcast/studio runtime.
2. **PubPartner Federation** — the persistent synchronization and memory layer.
3. **2i Backend** — the manuscript/editor service.
4. **Foresight** — the visual UI system being integrated into PubCast.

The architecture is fundamentally sound:

- PubCast owns live studio execution, avatars, cameras, recording, rooms, and AlexCore.
- PubPartner owns durable synchronization, conflict handling, and persistent memory.
- 2i owns manuscript editing and communicates with PubPartner.
- Foresight provides the spatial/visual interface layer for PubCast.

The primary work remaining is **integration**, not wholesale replacement.

The critical principle is:

> **Optional subsystems may fail without taking down the core system.**

That means:

- PubCast can operate without Pete.
- Studio controls can operate without WebSocket delivery.
- Cameras can fall back to generated/test frames.
- Voxel loading can fall back to local manifests.
- 2i can save locally when PubPartner is unavailable.
- PubPartner memory synchronization can fail without destroying the active conversation.
- Foresight can render a degraded/static UI when its backend is unavailable.

The integration should therefore be built around explicit boundaries, observable failures, deterministic fallback behavior, and tests that prove those properties.

---

# 2. Current System State

## 2.1 PubCast AI

**Runtime:** FastAPI  
**Port:** 8000

### Role

PubCast is the primary broadcast-studio runtime.

### Major components

- `main.py`
  - Application startup
  - Route registration
  - Runtime orchestration
- Hub
  - Message routing
  - History
- `RoomManager`
- `InferenceManager`
  - Ollama
  - GGUF / local inference
- `BotManager`
  - Pete
  - Sir Purfluous
  - Jeremy Cricket
- `CameraManager`
- `RecordingService`
- `GovernanceEngine`
  - Consent
  - Waiting room
  - Bans
- `AlexCore`
  - Emotional/EQ runtime
- `AlexJeremyBridge`
- `SessionResurrector`
- `UniversalMemorySystem`
- `EtherealAvatarManager`
- Vault
- `BlackBoxRuntimeWitness`

### UI subsystems

- Director Switcher
- Studio Control
- Dressing Room
- Avatar Foundry
- 2i Typewriter interface
- Production state machine

### Test state

The source document reports:

- 556 tests passing
- 25 pre-existing failures
- 7 additional failures/errors associated with test-order behavior

These numbers must be treated as the **observed baseline**, not simultaneously as the desired final baseline.

The execution plan should therefore use:

> **Current baseline:** 556 passing, 25 known failures, 7 test-order failures/errors.

The final target is:

> **Final baseline:** all intended tests passing, with no unexplained failures or errors.

---

# 3. PubPartner Federation

**Runtime:** FastAPI  
**Resident port:** 8001

## Role

PubPartner provides the durable synchronization layer underlying the persistent companion architecture.

It is important to distinguish:

- **Federation runtime** — synchronization and persistence.
- **Cartridge runtime** — personality, identity, conversational state, memory recall, and initiation.

The existing federation is not itself the complete companion.

## Portable and resident nodes

### Portable node

- Offline-first
- Disk-backed
- No network dependency during offline operation
- Synchronizes when connectivity is available

### Resident node

- Continuously available
- Provides synchronization services
- Acts as the local federation endpoint

Both use the same federation primitives.

## Federation components

- `engine.py`
  - Vector-clock synchronization
  - Patch-based updates
  - Conflict detection
  - Conflict resolution
- `service.py`
  - HTTP API
- `store.py`
  - SQLite persistence
- `protocol.py`
  - Change envelopes
  - Vector clocks
  - Entities
  - Conflicts
- `identity.py`
  - Node identity
  - Portable/resident role
- `memory.py`
  - Candidate memory capture
  - Promotion workflow

## Existing API

```text
POST /api/manuscript/commit
GET  /api/manuscript/{project_id}/{chapter_id}

POST /api/sync
POST /api/sync/pull
POST /api/sync/trigger
GET  /api/sync/conflicts

POST /api/memory/candidates
GET  /api/memory/candidates
POST /api/memory/candidates/{id}/promote
```

## Existing federation test state

The source reports:

> 14 federation tests passing.

These validate federation primitives but do not establish that the full companion runtime is complete.

---

# 4. 2i Backend

**Runtime:** Express.js  
**Port:** 8787

## Role

2i provides the manuscript/editor environment and communicates with PubPartner.

### Responsibilities

- Writer's Room
- Manuscript editing
- Thesaurus API
- LLM proxy
- Manuscript commits
- Conflict reporting
- Structured logging
- Timeout handling

## PubPartner integration

The existing integration:

```text
2i
  |
  | POST /api/manuscript/commit
  v
PubPartner
```

The request includes:

- `project_id`
- `chapter_id`
- `content`
- `base_version`
- additional commit metadata

The `base_version` is essential because it allows PubPartner to determine whether the writer edited against an outdated state.

## Failure behavior

If PubPartner is unavailable or times out:

```text
Writer
  |
  v
2i
  |
  X PubPartner unavailable
  |
  v
Local manuscript save
```

The editor should continue operating.

This is a core graceful-degradation requirement.

---

# 5. Integrated Topology

```text
                         ┌────────────────────────────┐
                         │          BROWSER           │
                         │                            │
                         │ Director Switcher          │
                         │ Writer's Room              │
                         │ Live Companion Chat        │
                         │ Foresight UI               │
                         └─────────────┬──────────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
                    ▼                  ▼                  ▼
             ┌────────────┐     ┌────────────┐     ┌───────────────┐
             │  PubCast   │     │     2i     │     │  Foresight    │
             │   :8000    │     │   :8787    │     │ UI Layer      │
             │            │     │            │     │               │
             │ AlexCore   │     │ Manuscript │     │ Trays         │
             │ Studio     │     │ Editor     │     │ Rooms         │
             │ Cameras    │     │ LLM Proxy  │     │ Polyhedron    │
             │ Recording  │     │            │     │ Renderer      │
             └──────┬─────┘     └──────┬─────┘     └───────┬───────┘
                    │                  │                   │
                    │                  │                   │
                    └──────────┬───────┴───────────────────┘
                               │
                               ▼
                     ┌─────────────────────┐
                     │ PubPartner Resident │
                     │       :8001         │
                     │                     │
                     │ SyncEngine          │
                     │ MemoryGate          │
                     │ Conflict Store      │
                     │ SQLite              │
                     └──────────┬──────────┘
                                │
                                │ federation sync
                                ▼
                     ┌─────────────────────┐
                     │ Portable PubPartner │
                     │      Node           │
                     │                     │
                     │ Offline-first       │
                     │ Sync on demand      │
                     └─────────────────────┘
```

---

# 6. Integration Boundaries

The system should maintain explicit ownership boundaries.

## PubCast owns

- Live session state
- Studio state
- Cameras
- Recording
- Avatars
- Live conversation execution
- AlexCore session state

## PubPartner owns

- Durable companion identity
- Durable memory
- Federation state
- Change history
- Conflict records
- Portable/resident synchronization

## 2i owns

- Manuscript editing
- Writer-facing conflict presentation
- Local manuscript fallback

## Foresight owns

- Visual spatial representation
- Tray geometry
- Room-specific presentation
- UI composition

The bridge between these systems should be explicit rather than allowing one subsystem to reach arbitrarily into another subsystem's internal state.

---

# 7. Deferred Wiring Inventory

The original document understated the number of deferred locations.

The detailed inventory identifies the following:

| Component | Deferred capability | Approx. locations |
|---|---|---:|
| `mocap_integration.py` | Pete/Rust pose-frame calls | 4 |
| `studio_control.py` | WebSocket broadcast | 5 |
| `studio_control.py` | Emergency buffer flush | 1 |
| `studio_control.py` | Recording save | 1 |
| `voxel_asset_manager.py` | Pete Enhanced preload | 1 |
| `cameras_advanced.py` | Real camera capture | 1 |
| `vault_engine.py` | Backup restoration | 1 |
| **Total** | | **14** |

The 2i → PubPartner manuscript call is **not deferred**; it is treated as an existing integration.

Therefore:

> Do not refer to these as "8 deferred spots."

Use **14 deferred locations** unless the actual code audit establishes a different count.

---

# 8. Workstream 1 — Resolve Test-Order Pollution

## Problem

The reported behavior is:

- affected tests fail when the full suite runs;
- the same tests pass when run individually.

That establishes test-order dependence, but it does **not yet prove** that FastAPI's internal router cache is the root cause.

The original plan prematurely identifies FastAPI internals as the likely culprit.

### Correct diagnostic sequence

1. Reproduce the failure deterministically.
2. Identify the first test after which global state changes.
3. Compare application state before and after that test.
4. Inspect:
   - middleware registration
   - route registration
   - global singletons
   - module-level caches
   - dependency overrides
   - lifespan state
   - event handlers
   - router state
5. Only then investigate framework internals.

### Instrumentation

Track:

```python
{
    "middleware_count": ...,
    "route_count": ...,
    "dependency_override_count": ...,
    "registered_event_handlers": ...,
    "singleton_state": ...,
}
```

The instrumentation should be test-only or debug-gated.

Do not add a permanent public debugging endpoint merely to diagnose the test suite.

### Success criterion

```text
Full suite:
0 unexplained failures
0 unexplained errors
```

No assumption should be made about the exact root cause until instrumentation establishes it.

---

# 9. Workstream 2 — Activate Deferred Calls Safely

The deferred calls should not all be blindly uncommented at once.

Use a three-stage activation model.

## Stage A — Contract tests

Verify:

```text
caller → interface → fallback
```

using mocks/stubs.

## Stage B — Feature-flagged real backend

Enable the real backend behind an explicit configuration flag.

Example:

```text
USE_REAL_CAPTURE=false
ENABLE_PETE_POSE=false
ENABLE_STUDIO_BROADCAST=false
```

## Stage C — Production default

Only after real-backend integration tests pass should the feature become the normal runtime path.

---

# 10. Mocap / Pete Integration

Required behavior:

```text
Mocap frame
    |
    +---- Pete available ----> send pose
    |
    +---- Pete unavailable --> retain mocap frame
```

Pete failure must not destroy the underlying mocap capture.

Test both:

1. `pete_engine is None`
2. `send_pose_frame()` raises

The test should verify both that:

- the operation does not raise;
- the mocap frame remains valid.

---

# 11. Studio Control

## WebSocket behavior

Local studio state should be authoritative.

Recommended ordering:

```text
User action
    ↓
Update local state
    ↓
Attempt WebSocket broadcast
    ↓
Broadcast succeeds
        OR
Broadcast fails → log + continue
```

This makes the fallback guarantee explicit.

Test:

```text
switch camera
    ↓
local state changes
    ↓
broadcast attempted
    ↓
broadcast fails
    ↓
local state remains correct
```

---

# 12. Microphone Detection

Hardcoded device IDs must be removed.

However, microphone enumeration should **not** be performed with `await` inside a normal `__init__`.

Use one of:

- synchronous enumeration during construction;
- asynchronous startup initialization;
- an explicit `initialize()` lifecycle method.

The preferred architecture is:

```text
construct object
      ↓
start application
      ↓
async initialize hardware
      ↓
publish ready state
```

The selected microphone should also be represented by a stable device identity where possible, rather than assuming that OS device index `3` or `1` remains stable.

---

# 13. Voxel Asset Loading

Desired fallback:

```text
Pete Enhanced available?
    |
    +-- yes --> preload scene through Pete
    |
    +-- no --> local manifest
```

If Pete fails after being available:

```text
Pete preload
    ↓
failure
    ↓
log warning
    ↓
local manifest
```

Test both branches.

---

# 14. Camera Capture

Desired behavior:

```text
Real capture enabled?
       |
       +-- no --> test/offline frame
       |
       +-- yes
              |
              +-- camera works --> real frame
              |
              +-- camera fails --> test/offline frame
```

The fallback must be observable so that a production operator cannot mistake synthetic frames for real camera input.

A useful state distinction is:

```text
REAL
FALLBACK
OFFLINE
ERROR
```

rather than silently returning a frame.

---

# 15. Recording and Vault

The original execution plan concentrates heavily on Pete, cameras, and WebSockets but under-specifies two other deferred operations:

- recording buffer flush;
- recording save;
- vault backup restoration.

These should be explicitly included in the same deferred-call workstream.

### Recording requirement

A successful recording operation should guarantee:

```text
capture
  ↓
buffer
  ↓
flush
  ↓
persist
  ↓
manifest/export verification
```

A failure during persistence should produce an explicit error state.

### Vault requirement

Backup restoration should be treated as a recovery operation, not a normal fallback.

It needs tests for:

- integrity violation;
- backup unavailable;
- backup corrupt;
- successful restoration.

---

# 16. PubPartner Cartridge Runtime

The federation engine and the companion cartridge should remain conceptually separate.

## Federation

Answers:

> How does durable state move and remain consistent?

## Cartridge

Answers:

> Who is this companion, what does it remember, how does it speak, and how does it behave across sessions?

The cartridge should therefore own:

- identity
- personality
- voice profile
- durable memory references
- conversation history
- session context
- initiation policy
- memory recall policy

---

# 17. Cartridge Identity

A minimal identity model can contain:

```text
name
voice_profile
personality_profile
relationship_state
memory_references
last_interaction
initiation_policy
```

However, `relationship_level: 0–100` should not be treated as an objective measurement unless the project defines exactly how that number is calculated.

If it remains, document it as an application-level heuristic.

Likewise, increasing the relationship level by:

```python
relationship_level += len(promoted_memories)
```

is too arbitrary to be a meaningful relationship model.

A better design is to separate:

```text
relationship state
+
memory count
+
interaction history
```

rather than deriving one directly from another.

---

# 18. Session Anchors

The cartridge may provide compact context anchors for session continuity.

Example structure:

```text
Identity
Relationship context
Small set of durable memory references
Recent interaction context
Current session focus
```

The important requirement is not a hard-coded token count.

The anchor should instead have:

- a configurable token budget;
- deterministic truncation;
- tests using the actual tokenizer for the target model.

The original "roughly 4 characters per token" calculation is acceptable for a sketch but should not be the production validation mechanism.

---

# 19. Conversation History

The proposed `ConversationHistory` object is currently an in-memory buffer.

Therefore it should not be described as "persistent conversation history" until it has a persistence backend.

Recommended boundary:

```text
ConversationHistory
        |
        +--> in-memory session cache
        |
        +--> durable history store
```

The history manager should support:

- append turn
- load session
- retrieve recent turns
- retrieve by session
- retrieve by time
- optionally retrieve by topic
- enforce retention policy

---

# 20. Alex ↔ PubPartner Memory Synchronization

This is one of the most important integration points.

Desired flow:

```text
User message
     ↓
AlexCore
     ↓
Response + structured session signals
     ↓
Memory candidate generation
     ↓
PubPartner MemoryGate
     ↓
Candidate
     ↓
promotion / approval
     ↓
durable memory
     ↓
future session recall
```

## Important correction

Do not make durable-memory extraction depend primarily on phrases in Alex's generated response such as:

```text
"remember"
"last time"
"always"
```

That creates a dangerous feedback loop:

```text
Alex says something
    ↓
system interprets Alex's statement as fact
    ↓
fact becomes memory
    ↓
future Alex sees memory
    ↓
Alex repeats it
    ↓
system reinforces it
```

Instead, memory candidates should be generated from structured context containing:

- user message;
- relevant conversation context;
- AlexCore signals;
- explicit user memory requests;
- confidence;
- source;
- timestamp;
- session ID.

The memory object should retain provenance.

Example:

```json
{
  "text": "...",
  "source": "user_statement",
  "session_id": "...",
  "confidence": 0.91,
  "candidate": true
}
```

That makes the memory system auditable.

---

# 21. User / Session Scoping

The proposed memory bridge accepts `user_id`, but the shown implementation does not actually use it when retrieving memories.

That must be fixed.

Memory operations need an explicit scope:

```text
cartridge_id
user_id
session_id
```

At minimum, durable companion memory must not become an unscoped global list.

Recommended conceptual hierarchy:

```text
Federation
  └── Cartridge
       └── User relationship
            └── Memory
                 └── Provenance
```

---

# 22. Memory Promotion

The existing MemoryGate concept is good:

```text
candidate
   ↓
review / policy
   ↓
promoted memory
```

The cartridge should consume **promoted memories**, not arbitrary candidates.

This creates an important safety boundary:

> Candidate memory is not truth.

Only promoted memory becomes part of durable companion context.

---

# 23. Bidirectional Alex Synchronization

The intended flow is:

```text
                 ┌─────────────────────┐
                 │      PubCast        │
                 │                     │
                 │      AlexCore       │
                 └─────────┬───────────┘
                           │
                     session signals
                           │
                           ▼
                 ┌─────────────────────┐
                 │     PubPartner      │
                 │                     │
                 │    MemoryGate       │
                 └─────────┬───────────┘
                           │
                    promoted memory
                           │
                           ▼
                 ┌─────────────────────┐
                 │      AlexCore       │
                 │  future context     │
                 └─────────────────────┘
```

The synchronization should be asynchronous where possible.

A temporary PubPartner outage should not block the live conversational response.

---

# 24. 2i Conflict Handling

The federation can detect conflicts, but the editor needs a useful human-facing representation.

Desired flow:

```text
Writer A
   ↓
2i
   ↓
PubPartner

Writer B
   ↓
2i
   ↓
PubPartner
   ↓
conflict detected
   ↓
conflict record
   ↓
2i conflict UI
```

The UI should show:

- field affected;
- local value;
- remote value;
- version information;
- provenance;
- conflict reason;
- available resolution action.

A simple `alert()` is sufficient as an initial diagnostic implementation, but should not be considered the final conflict UI.

---

# 25. Conflict Semantics

The vector-clock design is appropriate for determining causal relationships.

The documentation should explicitly distinguish:

```text
causally newer
```

from:

```text
concurrent
```

and from:

```text
same value / semantically equivalent
```

A conflict should not be generated merely because two versions differ.

The actual rule should be:

```text
same field
+
concurrent causal histories
+
different values
=
conflict candidate
```

Resolution policy should then be explicit.

Possible policies:

- manual resolution;
- field-specific merge;
- deterministic last-writer-wins;
- domain-specific merge.

The policy should never be implicit.

---

# 26. Foresight Integration

Foresight is currently described as a separate design system that needs to become a PubCast UI layer.

The integration should proceed in this order:

```text
Tray model
    ↓
Tray family validation
    ↓
Room routing
    ↓
Foresight renderer
    ↓
PubCast embedding
```

Do not start with the renderer.

The renderer is downstream of the data model.

---

# 27. Tray Family Contract

The system needs one authoritative mapping:

```text
TRAY_FAMILIES
```

The test should establish:

```text
Every known tray
    ↓
has exactly one valid family
    ↓
matches its configured family
```

Also test the inverse:

```text
Every configured family
    ↓
contains only known trays
```

This catches both:

- trays assigned to the wrong family;
- family definitions referring to nonexistent trays.

The reported "8 of 9 trays drifted" should remain an observed design/test finding until verified against the actual current configuration.

---

# 28. Room Routing

The proposed room mapping is coherent:

```text
Dressing Room
    - avatar foundry
    - pose library
    - wardrobe
    - 2i typewriter

Studio
    - camera presets
    - lighting
    - set selector
    - chat

Control Room
    - recording
    - mixer
    - timeline
    - export
    - emergency control
```

The room router should return structured tray definitions rather than merely strings where possible.

For example:

```json
{
  "name": "camera_preset_1",
  "family": "camera",
  "room": "studio",
  "enabled": true
}
```

That gives Foresight enough information to render without recreating backend knowledge.

---

# 29. Foresight API Contract

There should be one authoritative endpoint for room-aware tray retrieval.

Recommended:

```text
GET /api/foresight/room/{room_name}/trays
```

The renderer should consume that endpoint rather than independently querying a less-specific `/api/studio/trays` endpoint.

If `/api/studio/trays` must remain for compatibility, define it as a legacy/general endpoint and explicitly document the difference.

---

# 30. Foresight Renderer

The renderer should treat the API as untrusted input.

For each tray:

```text
family exists?
   |
   +-- yes --> render family
   |
   +-- no --> render generic fallback
```

The renderer should never crash because an unknown family was returned.

The original prototype also needs refinement before being treated as a working renderer:

- `LineSegments` does not automatically produce a closed polygon from six hexagon vertices.
- The shape library must cover all valid tray families.
- Unknown families currently risk producing `undefined`.
- Tray positioning is not defined.
- Room layout is not defined.
- Responsive resizing is not implemented.
- API failure only logs an error; the promised static fallback is not actually implemented.

---

# 31. Boot Sequence

The dependency ordering should be:

```text
1. PubPartner resident
       ↓
2. PubPartner health confirmed
       ↓
3. 2i backend
       ↓
4. PubCast
       ↓
5. Foresight/browser UI
```

However, PubCast should ideally be capable of booting even if PubPartner is unavailable.

Therefore:

> PubPartner should be started first for the integrated environment, but PubCast must not be architecturally dependent on PubPartner for basic startup.

That distinction is important.

---

# 32. Startup Readiness

Do not use fixed sleeps as the primary readiness mechanism.

Avoid:

```python
await asyncio.sleep(2)
```

Use health/readiness checks instead:

```text
start process
   ↓
poll health endpoint
   ↓
ready?
   ├── yes → continue
   └── no → timeout / diagnostic failure
```

This makes the E2E test deterministic across different machines.

---

# 33. Integrated End-to-End Test

The E2E test should verify actual behavior, not merely process startup.

Required sequence:

```text
1. Start PubPartner
2. Confirm PubPartner readiness
3. Start 2i
4. Confirm 2i readiness
5. Start PubCast
6. Confirm PubCast readiness
7. Submit manuscript
8. Verify manuscript exists in PubPartner
9. Create concurrent edit
10. Verify conflict behavior
11. Start Alex conversation
12. Verify response
13. Verify memory candidate exists
14. Promote memory
15. Start a new cartridge/session
16. Verify promoted memory is recalled
17. Execute recording workflow
18. Verify recording/export manifest
19. Shut down all processes cleanly
```

Each numbered step should have an actual assertion.

The test should not claim to validate a step that it does not assert.

---

# 34. Process Cleanup

The E2E test should use reliable cleanup:

```text
try:
    start systems
    run assertions
finally:
    terminate
    wait
    kill if necessary
    verify ports released
```

It should also avoid assuming that ports 8000/8001/8787 are free.

A test environment should preferably use dynamically allocated ports or a dedicated test configuration.

---

# 35. Error-Path Testing

Every optional subsystem needs two classes of tests:

## Unavailable

```text
backend = None
```

## Failing

```text
backend exists
backend raises exception
```

These are not equivalent.

Both must be tested.

Required fallback matrix:

| Subsystem | Backend unavailable | Backend fails |
|---|---:|---:|
| Pete/mocap | ✓ | ✓ |
| WebSocket | ✓ | ✓ |
| Microphone | ✓ | ✓ |
| Voxel/Pete Enhanced | ✓ | ✓ |
| Camera | ✓ | ✓ |
| Recording | ✓ | ✓ |
| Vault recovery | ✓ | ✓ |
| PubPartner memory | ✓ | ✓ |
| 2i manuscript sync | ✓ | ✓ |
| Foresight API | ✓ | ✓ |
| Cartridge persistence | ✓ | ✓ |

---

# 36. Graceful Degradation Definition

"Graceful degradation" should have a measurable definition.

A subsystem passes if:

1. the primary operation fails;
2. the failure is observable/logged;
3. the process remains alive;
4. the fallback activates;
5. the fallback produces a valid result;
6. the resulting state identifies the degraded condition where appropriate.

This is much stronger than merely asserting:

```python
assert result is not None
```

---

# 37. Performance Validation

Performance targets should be treated as engineering targets rather than universal truths.

Proposed initial targets:

```text
PubCast application initialization: < 5 seconds
Federation local conflict detection: < 100 ms
```

But these must be measured under defined conditions.

Document:

- hardware;
- Python version;
- FastAPI version;
- database state;
- dataset size;
- number of concurrent operations;
- whether the measurement includes process startup.

A `create_app()` timing test does not establish full runtime boot performance.

---

# 38. Federation Load Test

The concurrency test should use an async test function if it contains `await`.

It should also distinguish:

```text
100 concurrent independent writes
```

from:

```text
100 concurrent writes to the same entity
```

Those exercise very different paths.

Test both eventually.

---

# 39. Production Readiness Checklist

## Core infrastructure

- [ ] Full test-order failure diagnosed and fixed
- [ ] Full test suite clean
- [ ] PubPartner health/readiness verified
- [ ] PubCast startup verified
- [ ] 2i startup verified

## Deferred integrations

- [ ] Pete/mocap wired
- [ ] WebSocket broadcasts wired
- [ ] Microphone enumeration wired
- [ ] Voxel preload wired
- [ ] Real camera capture wired
- [ ] Recording flush wired
- [ ] Recording persistence wired
- [ ] Vault recovery wired

## Companion

- [ ] Cartridge identity persistence
- [ ] Voice profile
- [ ] Personality profile
- [ ] Durable conversation history
- [ ] Session context loading
- [ ] Memory candidate generation
- [ ] Memory promotion
- [ ] Promoted-memory recall
- [ ] AlexCore ↔ PubPartner synchronization
- [ ] Initiation policy
- [ ] Offline operation

## Federation

- [ ] Portable/resident sync
- [ ] Vector-clock behavior
- [ ] Conflict detection
- [ ] Conflict resolution
- [ ] Idempotency
- [ ] User/cartridge scoping
- [ ] Provenance

## 2i

- [ ] Manuscript commit
- [ ] Local fallback
- [ ] Conflict display
- [ ] Manual resolution
- [ ] Refresh/rebase behavior

## Foresight

- [ ] Tray family contract
- [ ] Room routing
- [ ] Renderer
- [ ] API integration
- [ ] Static/degraded fallback
- [ ] Responsive layout
- [ ] PubCast embedding

## Production validation

- [ ] End-to-end show simulation
- [ ] Recording/export verification
- [ ] Avatar GLB validation
- [ ] Ollama availability check
- [ ] Offline-browser behavior
- [ ] Performance validation
- [ ] Failure-path validation

---

# 40. Recommended Four-Phase Execution Plan

## Phase 1 — Stabilize

**Goal:** Establish a trustworthy baseline.

### Tasks

1. Record exact current test counts.
2. Reproduce test-order failures.
3. Instrument global application state.
4. Identify actual state leak.
5. Fix root cause.
6. Confirm full-suite stability.

### Exit condition

```text
Full suite passes consistently in the same environment.
```

---

# Phase 2 — Activate Existing Integrations

**Goal:** Turn already-written deferred functionality into tested functionality.

### Tasks

1. Mocap/Pete
2. Studio WebSocket
3. Microphone enumeration
4. Voxel preload
5. Camera capture
6. Recording flush/save
7. Vault recovery

For every task:

```text
contract test
    ↓
failure-path test
    ↓
real-backend test
    ↓
feature enabled
```

### Exit condition

Every deferred integration has:

- a real implementation;
- a fallback;
- tests for both.

---

# Phase 3 — Complete Companion Integration

**Goal:** Transform PubPartner federation into the durable companion layer described by the architecture.

### Tasks

1. Cartridge identity
2. Voice/personality configuration
3. Durable conversation history
4. Session anchor generation
5. Memory candidate pipeline
6. Memory promotion
7. AlexCore bridge
8. User/cartridge scoping
9. Promoted-memory recall
10. Initiation policy
11. Offline behavior
12. Portable/resident synchronization

### Exit condition

A session can:

```text
start
  ↓
load identity
  ↓
load promoted memories
  ↓
conduct conversation
  ↓
produce memory candidates
  ↓
promote selected memories
  ↓
end
  ↓
start again
  ↓
recover durable state
```

---

# Phase 4 — Foresight + Production Hardening

**Goal:** Finish the visual integration and prove the entire system.

### Tasks

1. Tray family contract
2. Room routing
3. Foresight renderer
4. API integration
5. Degraded UI
6. PubCast embedding
7. Full E2E workflow
8. Performance validation
9. Failure-path testing
10. Documentation

### Exit condition

The integrated system can run the complete workflow without relying on hidden assumptions.

---

# 41. Suggested Repository Structure

A clean separation could look like:

```text
pubcast/
├── modules/
│   ├── alex_federation_bridge.py
│   ├── pubpartner_sync_hook.py
│   ├── mocap_integration.py
│   ├── studio_control.py
│   ├── voxel_asset_manager.py
│   └── cameras_advanced.py
│
├── static/
│   └── foresight/
│       ├── shell.html
│       ├── renderer.js
│       └── tray-layout.js
│
└── tests/
    ├── integration/
    ├── fallback/
    └── foresight/

pubpartner/
├── pubpartner_federation/
│   ├── engine.py
│   ├── service.py
│   ├── store.py
│   ├── protocol.py
│   ├── identity.py
│   └── memory.py
│
└── cartridge/
    ├── runtime.py
    ├── identity.py
    ├── voice.py
    ├── history.py
    ├── memory.py
    └── initiation.py

2i-backend/
├── server.js
├── routes/
└── tests/
```

The exact structure can remain different if the existing repository already has a strong convention. The important thing is the conceptual separation.

---

# 42. Documentation Rules

The project documentation should distinguish three states:

### Implemented

The code exists and has been verified.

### Implemented but not integrated

The code exists, but the complete runtime path has not yet been connected.

### Planned

The architecture describes what should be built, but implementation does not yet exist.

Do not describe planned code as "ready."

Do not describe passing unit tests as proof of production readiness.

Do not describe a fallback as working until the failure path has actually been tested.

---

# 43. Production Standard

The intended quality bar remains:

- No silent failures
- No unexplained global state
- No placeholder implementations presented as complete
- Critical paths covered by tests
- Failure paths tested
- Integration paths tested with real backends
- Conflicts reproducible in isolation
- Durable state has provenance
- Optional services do not take down the core runtime
- Documentation reflects actual implementation state

The strongest version of the standard is:

> **The system should fail loudly at the boundary, gracefully inside the runtime, and never silently corrupt durable state.**

---

# 44. Final Architecture

The resulting system should behave conceptually like this:

```text
                         PUBCAST
                    ┌────────────────┐
                    │ Live Runtime   │
                    │                │
                    │ AlexCore       │
                    │ Studio         │
                    │ Cameras        │
                    │ Recording      │
                    │ Avatars        │
                    └───────┬────────┘
                            │
                   live/session signals
                            │
                            ▼
                    ┌────────────────┐
                    │  PUBPARTNER    │
                    │                │
                    │ Cartridge      │
                    │ MemoryGate     │
                    │ Federation     │
                    │ Conflict Store │
                    └───────┬────────┘
                            │
                    durable synchronization
                            │
                ┌───────────┴───────────┐
                ▼                       ▼
        Portable Node            Resident Node
        offline-first            always available


        2i
         │
         │ manuscript commits
         ▼
     PubPartner
         │
         │ conflict/version state
         ▼
        2i


        Foresight
            │
            │ room/tray state
            ▼
         PubCast
```

The key architectural idea is therefore not "three applications glued together."

It is:

> **PubCast is the live body. PubPartner is the durable continuity layer. 2i is the writing surface. Foresight is the spatial interface.**

Each has a clear responsibility, and the bridges between them carry explicitly defined state rather than leaking internal implementation details.

---

# 45. Immediate Next Actions

Do these in order.

### 1. Establish the real baseline

Run the complete test suite and record:

```text
passing
failing
errors
skipped
xfail
```

Do not use the previous 556/575 numbers as assumptions.

### 2. Fix test-order pollution

Do not patch FastAPI internals until the instrumentation demonstrates that FastAPI is actually responsible.

### 3. Inventory the 14 deferred locations

Mark each:

```text
DEFERRED
TESTED
WIRED
REAL-BACKEND VERIFIED
PRODUCTION ENABLED
```

### 4. Wire the low-risk fallbacks

Mocap, WebSocket, voxel, and camera paths are good candidates.

### 5. Complete the cartridge boundary

Before writing more companion logic, establish:

```text
Cartridge
    ↕
MemoryGate
    ↕
Federation
```

### 6. Fix memory provenance/scoping

This should happen **before** automatic memory capture is enabled.

### 7. Establish the Foresight API contract

Decide which tray endpoint is authoritative before implementing the renderer.

### 8. Build the real E2E test

Make every claimed step an actual assertion.

---

# 46. Final Success Definition

The system is ready when all of the following are true:

```text
✓ Full test suite is clean
✓ Test-order behavior is understood
✓ All deferred integrations are explicitly accounted for
✓ Every optional backend has a tested fallback
✓ PubPartner has a real cartridge runtime
✓ Durable memory has provenance and scope
✓ AlexCore can exchange approved memory with PubPartner
✓ 2i conflict handling is observable and actionable
✓ Foresight consumes a defined API contract
✓ Room-specific tray routing works
✓ Full E2E workflow passes
✓ Recording/export is verified
✓ Portable/resident synchronization passes
✓ Performance measurements are reproducible
✓ No subsystem silently loses durable state
✓ Documentation matches actual implementation state
```

**That is the finish line.**

Not "the code looks complete."

Not "the unit tests are green."

The finish line is:

> **The integrated system behaves coherently when everything works, when individual components fail, and when the system is restarted and asked to remember what happened before.**