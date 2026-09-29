PUBCAST ENGINEERING MANUAL — ADDITIONAL CHAPTER
Chapter: Review, Interpretation, and Hardening of the Existing Rule Set

Purpose of This Chapter
The original manual (Sections I–VIII, Appendices A–B) establishes the operating rules for any AI coding agent working on PubCast. This chapter is a rule-by-rule review of that manual: which rules are sound as written, which need rephrasing to close ambiguity, which have a structural problem the wording alone can't fix, what's missing, what needs more research before it can be trusted, and — where relevant — whether the existence of the rule points at a deeper workflow issue that a tool or process change could make unnecessary. This chapter does not replace any existing rule. It sits alongside the original text as interpretive and hardening material.

Section I: Core Philosophical Rules & Boundaries — Review

Rules 1–6 (Understand PubCast before touching it; PubCast has a history; messy ≠ wrong; local folder is source of truth; a repo is not automatically a seed; never substitute a reconstruction for requested files)
Status: Sound as written.
Interpretation: These six rules are the foundation the rest of the manual depends on. The single idea underneath all of them is: the AI must ask what the developer wants the repository to represent, and must never silently substitute its own judgment for that answer. Every other rule in the manual is a special case of this one. These should be treated as non-negotiable and applied literally, not paraphrased in practice.
Nothing to add.

Rule 7 ("Do Not Modify" is stronger than it sounds)
Status: Needs rephrasing — the boundary is underspecified.
Problem: The rule permits ".gitignore or README.md" as "standard repository management" but doesn't define the full category. In practice an agent will also encounter the question of whether it may add a LICENSE file, a .gitattributes file, a CONTRIBUTING.md, CI/workflow config, or an EDITORCONFIG file without asking.
Hardening: Replace the implicit boundary with an explicit whitelist. Files an AI may create without asking: .gitignore, README.md (only if none exists), and nothing else. Every other new file — including LICENSE, CI config, .gitattributes — requires the developer's explicit go-ahead first, stated in the same message as the request or given in response to a direct question. This removes the judgment call entirely rather than asking the agent to reason about what counts as "standard."

Rule 8 (Anti-Placeholder Mandate)
Status: Sound, and one of the two or three most important rules in the whole manual.
Nothing to add here beyond what Section VIII already proposes mechanically (see below).

Rule 9 (Scope Locking)
Status: Sound as written.

Rule 10 (Reversibility & Small Mechanical Changes)
Status: Sound, but abstract. It says "prefer atomic commits" without defining the commit boundary for this specific codebase.
Hardening: Define default commit boundaries explicitly: one commit per subsystem touched (runtime, UI, world/assets, docs) per session, never one commit spanning more than one subsystem unless the task itself is cross-cutting and was described that way by the developer.

Rule 11 (Never Hide a Structural Change)
Status: Sound as written.

Rule 12 (Never Optimize for the AI's Convenience)
Status: Sound in spirit, weak as an enforceable rule — there's no way to test from the outside whether an agent's suggestion to simplify something is "for its own convenience" or a genuine improvement it's flagging honestly.
Interpretation: This rule is best understood not as a standalone directive but as the *reason* Rules 9 and 11 exist. Its practical enforcement mechanism is really Rule 9 (stay in scope) and the general instruction elsewhere in this manual that the agent may propose an idea but must not act on it without the developer choosing it. Treat Rule 12 as context/motivation rather than a separately checkable rule.

Section II: File System, Layering & Repository Hygiene — Review

Rules 13–21 (three-layer model, .gitignore semantics, history is not retroactively erased, 100 MiB limit, baggage/ protocol, generated-output protocols by language, the Regeneration Test, preserve the real source tree, large files aren't automatically unnecessary)
Status: Sound, and the best-specified section of the manual. The Regeneration Test (Rule 19) in particular is the single most operationally useful rule in the document — it's a yes/no test an agent can actually run against a specific file rather than a general principle it has to interpret.
Nothing to add.

Rule 22 (Roles of ZIP Archives)
Status: Needs more detail — the four categories (backup snapshot, release asset, dependency archive, temporary handoff) are correctly identified, but there is no procedure for determining which category an unlabeled ZIP actually belongs to.
Hardening: When a ZIP's role is not stated by the developer, the agent must determine it by, in order: (1) checking whether anything in the codebase currently references or imports its contents, (2) checking whether a matching extracted/unpacked version of its contents already exists elsewhere in the tree, (3) checking the filename and any accompanying notes or commit messages for stated purpose. If the role is still unclear after this check, the agent asks the developer rather than guessing, and defaults to treating the file as Historical Baggage (keep locally, exclude from git) until told otherwise — Historical Baggage is the safest default because it is the only one of the four categories that cannot cause data loss if the guess is wrong.

Rule 23 (Web Uploads vs Command-Line Git)
Status: Sound as written.

Section III: Architecture, State Ownership & Validation — Review

Rules 24–26 (learn architecture, read before editing, single source of truth)
Status: Sound, standard good practice, nothing PubCast-specific required.

Rule 27 (The 7-Level Validation Hierarchy) — combined with Rules 31–32 (Execution Boundary Mandate, Eradication of Simulated Verification)
Status: This is the one real structural problem in the manual, and it cannot be fixed by rephrasing either rule individually — it has to be resolved by deciding which one governs.
The problem, stated plainly: Rule 27 asks for verification up through Level 7 (service startup, runtime integration, user-visible behavior, and recovery after restart). Rules 31 and 32 say the AI has zero execution privileges by default and must never fabricate or simulate having run something. Read together and taken literally, an AI following this manual can honestly satisfy Levels 1 and 2 only (does it parse, do the imports resolve) — everything above that requires an execution environment the manual says, by default, doesn't exist. If an agent isn't told which rule wins, it will either quietly claim more verification than it actually performed (violating Rule 32) or silently stop at Level 2 and let the developer believe more was checked than was (also a form of the same problem, just by omission instead of fabrication).
Resolution — this is the interpretation this manual now adopts: Levels 1–2 are the AI's responsibility and must be performed before any code is handed over, every time, no exceptions. Levels 3–7 are the AI's responsibility only when it has a verified, connected execution bridge for this specific session — and if it does not, the AI's job at Levels 3–7 is not to skip them silently but to produce an explicit, numbered list of manual verification steps the developer needs to run themselves, phrased as commands or actions, not as vague suggestions. The AI states plainly which levels it verified and which levels it is handing to the developer to verify, every single time it delivers code — this replaces the ambiguity with a mandatory disclosure.

Rule 28 (Preflight & Doctor Infrastructure)
Status: Sound as written.

Rule 29 (Programmatic Layout & Geometry Verification)
Status: Sound, good specific practice for this project given the UI/animation work involved.

Rule 30 (Crash Isolation Protocol)
Status: Sound as written.

Section IV: AI Operational Protocols & Safety Controls — Review

Rule 31 (Execution Boundary Mandate)
Status: Sound in substance; the mechanism specified is weaker than it looks. Requiring the AI to output a literal "[MODE: STATIC ARCHITECTURAL ANALYSIS...]" header at the start of a session is a announcement, not an enforcement mechanism — nothing forces it to actually be typed or to actually be honored afterward.
Interpretation: What actually does the work is Rule 32's behavior (never fabricate verification), not Rule 31's header. The header is harmless to keep as a session-opening convention but should not be relied upon as the thing that prevents the failure mode — the failure mode is prevented by the AI's behavior throughout the session, not by a string at the top of it.

Rule 32 (Eradication of Simulated Verification)
Status: Sound, and this is a rule this manual (and this chapter's resolution of Rule 27, above) both depend on absolutely. No changes needed.

Rules 33–34 (Conversational history is binding context; the developer's explicit account beats AI assumptions)
Status: Needs a caveat — as written, these rules are correct for developer *preferences and intent* and risky if applied without qualification to developer *factual claims about what code currently does*.
Hardening: Split the two cases explicitly. When the developer states a preference, a boundary, or an account of what happened in a past session ("we tried that architecture and it broke routing," "a previous session made this into a seed repo and that was wrong") — that is binding, full stop, no argument, no request for proof. When the developer states a claim about the current behavior of the code itself ("this function already handles X," "the config file is at path Y") — the AI should treat that as a strong prior, check it against the actual files when it's about to act on it, and if the files show something different, say so plainly and let the developer decide how to proceed, rather than silently overriding what it sees or silently deferring to a claim that turns out to be wrong. This protects against the specific failure mode where a developer's memory of a prior session is imperfect and the AI's silent deference compounds the error instead of catching it.

Rule 35 (50-Turn Context Reset Protocol & HANDOFF_MANIFEST.md)
Status: Sound, and genuinely the best structural idea in the whole manual — it's the one rule that reduces reliance on the AI "remembering" to follow the other rules, by making the state explicit and external instead of dependent on conversational memory.

Rule 36 (Inter-Model Handoff Contracts)
Status: Sound but underspecified on its own — the template lives in Appendix A and should be treated as the literal required content of "Model Hand-Off Header," not as an example.

Rule 37 (Response Truncation Protocol)
Status: Sound as written.

Section V: Git Operations, PowerShell & Shell Safety — Review

Rules 38–45 (dry-run first, force-push discipline, warnings vs fatal errors, terminal output isolation, shell-neutral pathing, one-command delivery, post-operation verification, push signatures)
Status: All sound. This is the most mechanically precise section of the manual and needs no interpretation — it's already written as direct, testable procedure. One open assumption worth confirming rather than leaving implicit: Rules 42–43 assume PowerShell/Windows as the primary shell. If that's still accurate, no change needed; if the working environment has changed, this section needs updating to match, since these rules are wrong (not just imprecise) on a different shell.

Section VI: Handoff, Upload & Integration Rules — Review

Rules 46–49 (integration means placement not reinvention; filenames are evidence not architecture; duplicate file investigation protocol; timestamp/"latest" ambiguity)
Status: Sound, and this cluster of rules combined with Rule 22 forms one coherent procedure for handling any ambiguous or duplicate artifact. This chapter's hardening of Rule 22 above (check references, check for an existing unpacked version, check filename/notes, then ask, defaulting to the safest non-destructive category) is written to apply uniformly across Rules 22 and 46–49 — they should be read as one combined procedure, not four separate ones.

Rules 50–51 (documentation is part of system memory; recovery documentation authority)
Status: Sound as written.

Rule 52 (Clarifying "Clean Repo" Intent)
Status: Sound as written; the four-option menu (generated artifacts / untracked backups / secrets / reorganization) is a good disambiguation tool and should be used verbatim whenever "clean this up" or equivalent phrasing is used by the developer.

Section VII: PubCast Core Engineering Philosophy — Review

Rule 53
Status: Sound as a compressed restatement of the whole manual; nothing new to evaluate.

Section VIII: Structural Remedies & System Safeguards Against AI Hallucination — Review

Rules 54–56 (Iteration Wallet pre-parser, Multi-Model Generator/Auditor architecture, BlackBox immutable evidence logging)
Status: These describe infrastructure, not behavior an AI can simply choose to follow — this is the key distinction this chapter draws. Rules 1–53 and Rule 57 are things an AI can honor directly, in how it acts, in every session, starting now. Rules 54–56 describe *tools that would need to exist and be wired into the workflow* before they can do anything. Until and unless that infrastructure exists, these three rules are not currently enforceable by an AI simply reading and trying to comply with this manual — no amount of good-faith effort from the AI substitutes for the mechanical check the tool would perform.
Recommendation: Keep Rules 54–56 in the manual as the target state, but mark them explicitly as infrastructure to be built, separate from the rules that are already in effect. This isn't a demotion of the ideas — the underlying insight (don't rely on natural-language compliance alone; build a mechanical check that doesn't depend on the model behaving correctly in the moment) is the correct one, and is the single biggest lever available for actually reducing mistakes rather than just documenting the standard to avoid them. It just means, until that tooling exists, the actual safeguard operating in any given session is the AI's direct compliance with Rules 1–53 and 57, plus the developer reviewing every diff before it's accepted — not Rules 54–56, which aren't active yet.

Rule 57 (Tool-Calling Over Free Text)
Status: Sound, and unlike Rules 54–56, this one is achievable now within an ordinary AI coding session — using structured, scoped file-edit operations (targeted find-and-replace against an exact match, rather than freehand rewriting of a whole file from memory) rather than regenerating entire files from scratch by "remembering" what they contained. This should be treated as standard operating procedure going forward, not a future goal.

What the Manual Is Missing

1. Secrets and credentials. Beyond the passing mention in Rule 52 (Option C: "strip untracked secrets/keys"), there is no standing rule requiring a check for API keys, tokens, passwords, or credentials before any commit or push. Given this manual explicitly covers pushing to GitHub, this is a real gap, not a nice-to-have.
Added rule (Rule 58, proposed): Before any commit or push, the AI must scan the changed files for patterns consistent with credentials, API keys, tokens, or connection strings containing embedded passwords. If any are found, the AI stops, flags the exact file and line to the developer, and does not proceed with the commit or push until the developer confirms how to handle it. This check runs every time, not only when the developer asks for a "clean repo."

2. A tiebreaker principle for when rules conflict. Rule 27 vs. Rules 31–32 is not the only place two rules could pull in different directions (for example, Rule 33's "developer's account is binding" and the qualification this chapter adds to it). Rather than resolve conflicts case by case as they're discovered, this chapter proposes a standing principle:
Added rule (Rule 59, proposed): When two rules in this manual appear to conflict, the AI does not silently pick one and proceed. It states the conflict plainly, states which rule it intends to follow and why, and gives the developer the chance to override before continuing — the same way any other ambiguity in this manual is meant to be handled per Section I, Rule 1.

What Needs More Research

Rules 54–56 need the most groundwork before they can be treated as operative: specifically, whether "Iteration Wallet," the multi-model Generator/Auditor swap, and "BlackBox" logging refer to tooling that already exists in some form versus tooling that needs to be built from scratch. That answer changes the priority — if any of it already exists, wiring it in is a near-term task; if none of it exists, the practical safeguard for the time being is human review of every diff, which this manual already implies but doesn't currently state as the explicit fallback.

Does the Need for These Rules Point at a Bigger Workflow Problem?

Yes, and it's the same underlying issue surfacing in several different rules rather than fifty-seven unrelated problems. Rules 1, 6, 9, 11, 12, 38, and 39 are all, from different angles, hedges against the same risk: an AI given a large unit of work will sometimes take an action the developer didn't ask for and won't notice until much later. The rule-based fix — write a rule telling the AI not to do that — depends entirely on the AI remembering and correctly applying the rule in the moment, every time, with no way for the developer to verify that happened until after the fact.

A structural fix would not depend on that. Concretely, and cheaper than the custom tooling implied by Rules 54–56: git pre-commit hooks that block any commit touching more than a small, defined number of files without an explicit override; branch protection on main so nothing lands without being reviewed as a diff first, even in solo work; and a hard requirement that no local execution or destructive command runs without the dry-run/verification steps in Rules 38 and 44 having been shown first. None of that requires trusting the AI to remember the rule — it makes the risky action mechanically harder to take by accident, for any agent, human or AI, in any session. This doesn't make the rules in Sections I–VII unnecessary; it makes them enforced by more than good intentions, which is the gap this whole manual exists to close in the first place.
