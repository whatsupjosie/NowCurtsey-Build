# Spark Assignment — PubCast UI Functional Hardening & UAT

## Mission
Enhance and harden the UI PubCast already has. Do NOT redesign it, replace it, rebuild it from scratch, swap frameworks, or use this assignment as permission for broad refactoring.

**Preserve first. Repair second. Extend only where required by the stated functionality.**

The existing visual design and interaction model are the baseline. This assignment is about whether the UI actually works reliably.

## Mandatory scope rule
Before changing a UI subsystem, inspect its existing implementation and intended behavior. If it works, leave it alone unless a test demonstrates a defect relevant to this assignment.

Prefer the smallest local repair that makes the existing behavior dependable.

Do not:
- replace the window manager because another design is cleaner;
- restyle the application;
- change branding, colors, typography, or general visual identity;
- reorganize unrelated code;
- rename established concepts;
- replace working components;
- redesign PubCast architecture;
- change Conversation Engine/AI behavior;
- perform broad dependency upgrades;
- delete legacy/donor material merely because it appears inelegant.

If a defect appears to require structural redesign, document the evidence and stop at that boundary rather than silently redesigning the system.

## Primary work
Systematically test, repair, and regression-cover the existing UI interaction layer.

### Window behavior
Verify and repair, as applicable:
- open/close
- minimize/restore
- maximize
- drag
- resize
- focus and z-order
- workspace-edge bounds
- window-to-window collision behavior already intended by PubCast
- docking/undocking if implemented
- position/size restoration
- minimum/maximum dimensions
- duplicate windows
- multiple simultaneous windows
- repeated open/close/resize cycles
- app/workspace resize while child windows are open

Windows must not become unreachable, trapped, invisible, impossibly small, permanently behind another surface, or stranded outside the usable workspace.

### Menus and controls
Inventory every existing menu, button, toggle, selector, tab, transport control, navigation control, close/minimize control, room/world control, chat control, settings control, file/open control, contextual menu, and relevant keyboard action.

For each:
1. determine intended behavior from code/docs;
2. exercise it;
3. verify state changes;
4. repeat it;
5. test unavailable/error conditions;
6. repair defects within scope;
7. add regression coverage where practical.

Rendering is not proof of functionality.

### Workspace/reference surfaces
Exercise existing mechanisms for PubCast windows to host or reference, where supported:
- browser/web content;
- local HTML/web content;
- video/reference media, including FFmpeg-backed paths where present;
- images;
- text;
- PDFs/documents;
- local files;
- Iteration Wallet;
- PubCast tools/panels.

Do not build every conceivable file handler. Determine what exists, make its plumbing reliable, and report genuinely missing capability. If the OS/framework prevents direct embedding of an external application, document that boundary rather than inventing a giant workaround.

### Content/window interaction
For hosted content, test resize, minimize, restore, move, cover/uncover, focus changes, file/content changes, media start/stop, close/reopen, multiple content types, and containing-window closure. State and controls must remain coherent.

### Failure testing
Deliberately test missing/unsupported/malformed files, failed media, unavailable web content, unavailable subsystem/Iteration Wallet, duplicates, interrupted operations, and invalid window states. Failure in one surface must not destabilize the rest of PubCast.

## Stress and torture testing
Create repeatable stress tests: rapid open/close, repeated resize, edge dragging, overlap many windows, minimize/restore in changing order, rapid focus changes, close focused/background windows, load then resize content, restore saved workspace, and awkward action sequences.

Look for stale state, orphaned/invisible windows, z-order errors, clipping, broken hitboxes, collision/resize loops, UI/backend state disagreement, accumulating listeners, and resource leaks.

Create one deliberately chaotic power-user torture scenario that combines many windows, movement, resize, overlap, media, reference content, tool switching, minimize/restore, out-of-order closure, reopen, and at least one recoverable failure. PubCast must remain usable afterward.

## Testing method
Automate what is reasonably automatable, especially geometry/state transitions, collision/bounds calculations, menu actions, restoration, content lifecycle, focus/z-order, duplicate handling, and failure recovery.

Do not substitute unit tests for actual UI interaction testing. Use both.

For every bug:
1. reproduce;
2. reduce to smallest reliable reproduction;
3. identify responsible component;
4. add regression test where practical;
5. make smallest repair;
6. rerun reproduction;
7. rerun surrounding regression tests;
8. record change and evidence.

## Human User Acceptance Testing
Prepare a serious numbered UAT suite with realistic workflows and expected outcomes, not “click button; button works.”

Include at least:
- normal PubCast conversation workflow;
- multiple chat windows;
- browser/research/reference workflow;
- video-reference workflow;
- Iteration Wallet workflow;
- mixed-media workspace;
- heavy multitasking;
- workspace resize;
- minimize/restore;
- repeated tool switching;
- failure/recovery;
- long-running session;
- chaotic power-user/torture session.

A representative research workflow should exercise browser/reference + Iteration Wallet + PubCast chat side by side, resizing and moving surfaces, minimizing/restoring one, closing another, and verifying retained state.

## Evidence and deliverables
Produce:
1. Functional UI audit.
2. Complete control inventory with verified status.
3. Bug/fix ledger: reproduction, cause, smallest fix, verification.
4. Automated regression tests.
5. Human UAT package with numbered scenarios and expected results.
6. Known limitations and architectural boundaries.
7. Changed-file manifest with reason for every change.
8. Exact final regression results.

Do not claim tests were run if they were not actually executed.

## Definition of done
Not “it looks good” and not “it launches.”

Done means the existing PubCast UI has been systematically exercised, menus and controls tested, window behavior hardened, in-scope defects repaired without redesigning the product, regression coverage added where practical, and a human UAT suite exists that can expose anything Spark missed.

**Enhance what exists. Do not remake it. Make it dependable.**
