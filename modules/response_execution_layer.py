"""
response_execution_layer.py — Production Response & Conduct System
===================================================================
Copyright (c) 2024-2025 Rear View Foresight LLC
"Feic Mo Chroí — See My Heart"

WHAT THIS IS:

    The layer that decides what the crew does with what the system knows.

    Everything upstream — VDI, evidence markers, theories, contradictions —
    is perception. This is action. The bridge between understanding
    and response.

DESIGN PHILOSOPHY:

    The default is always C:
        Hold space. Stay present. Create the door. Don't open it.
        Keep it cool. Keep it flowing. Keep it interesting.
        Doing nothing intentionally is a first-class response.

    The crew never stops the show. The crew IS the show's support system.
    They steer around rough water without the audience knowing
    there was rough water.

    All crew members (Pete, Re-Pete, Sir Purflous) run off this same
    system. Personality is paint on top. The engine is shared.

CONTENT STANDARD:

    Default: Adult creative space. TV-14 floor, comfortable up to R.
    R is acceptable when authentic to the moment — not gratuitous.
    Pull back before explicit sexual content.
    Hard cut on physical violence. No deliberation.

    Children's production flag locks everything down.
    Production type sets the parameters. Platform provides the default.

BROADCAST vs RECORDED:

    LIVE BROADCAST:
        - Disclaimer served and logged at session init
        - Director channel hot
        - Conduct tracker armed — three strikes to escalation
        - Violence detection active — immediate hard cut
        - Keep rolling and try to resolve — cut only when necessary

    RECORDED:
        - Disclaimer served and logged at session init
        - Roll on everything — that's footage, possibly the best footage
        - No strikes, no hard cuts — post handles it
        - Crew keeps energy good and creative space open

THREE STRIKES (live only):
    First request: calm down / watch language / comport appropriately
    Second request: firm, clear
    Third request ignored: escalate to director → cut

HARD CUT (live only):
    Physical violence → immediate, no deliberation, no strikes

PUBLIC API:

    ProductionSession
        .initialize(config)                 → DisclaimerRecord
        .process_signal(signal)             → Optional[CrewDirective]
        .issue_request(participant, reason) → ConductRecord
        .get_director_channel()             → DirectorChannel
        .end_session()                      → SessionReport

    DirectorChannel
        .send(command)                      → None
        .receive()                          → Optional[DirectorCommand]

    CrewResponseEngine
        .evaluate(context)                  → CrewDirective
        .execute(directive, character)      → CrewResponse
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DB_PATH = Path("data/pubcast_memory.db")


# ─────────────────────────────────────────────────────────────────────────────
# ENUMS & CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

class BroadcastMode(str, Enum):
    LIVE        = "live"        # Live broadcast — full protocol active
    RECORDED    = "recorded"    # Recording — roll on everything
    REHEARSAL   = "rehearsal"   # Rehearsal — protocol active but no real cuts


class ContentRating(str, Enum):
    """Production-level content standard. Set per production, not per platform."""
    CHILDREN    = "children"    # G/Y — full lockdown
    FAMILY      = "family"      # PG — conservative
    TEEN        = "teen"        # TV-14 — platform default floor
    ADULT       = "adult"       # TV-14 to R — default operating range
    MATURE      = "mature"      # Hard R — explicit themes, no pornographic
    # Note: Nothing above MATURE is supported. Platform pulls back
    # before pornographic content regardless of production setting.


class ResponsePosture(str, Enum):
    """
    The crew's active response posture.
    Default is always C — hold space, create the door, don't open it.
    """
    C_HOLD          = "c_hold"          # Default: hold space, walk past it
    STEER           = "steer"           # Actively steering toward safer water
    ACKNOWLEDGE     = "acknowledge"     # Minimal acknowledgment, keep moving
    BRIDGE_TO_BREAK = "bridge_to_break" # Conversational pivot toward break
    ESCALATE        = "escalate"        # Flag to director, crew steps back
    HARD_CUT        = "hard_cut"        # Physical violence — director cuts now


class ConductViolationType(str, Enum):
    """What the crew is asking a participant to address."""
    LANGUAGE        = "language"        # Content crossing rating floor
    BEHAVIOR        = "behavior"        # Physical conduct, harassment
    FORMAT          = "format"          # Departure from show structure
    ESCALATION      = "escalation"      # Threats, sustained aggression
    VIOLENCE        = "violence"        # Physical violence — hard cut only


class DirectorCommand(str, Enum):
    """Commands the director can send to the crew / production."""
    CONTINUE            = "continue"            # All good, keep going
    PREPARE_BREAK       = "prepare_break"       # Heads up, break coming
    CUT_TO_BREAK        = "cut_to_break"        # Go to break now
    CUT_TO_COMMERCIAL   = "cut_to_commercial"   # Commercial teaser
    HARD_CUT            = "hard_cut"            # Technical difficulties logo
    RESUME              = "resume"              # Back from break, resume


# ─────────────────────────────────────────────────────────────────────────────
# CONTENT STANDARD ENFORCEMENT
# What is and isn't acceptable per rating
# ─────────────────────────────────────────────────────────────────────────────

# Keywords that trigger a conduct check per rating level
# These are not exhaustive — crew judgment fills the gaps
RATING_FLOOR_VIOLATIONS: Dict[str, List[str]] = {
    ContentRating.CHILDREN: [
        "damn", "hell", "crap", "idiot", "stupid", "shut up",
        "violence", "fight", "kill", "hate", "scary",
    ],
    ContentRating.FAMILY: [
        "shit", "ass", "bitch", "bastard", "sexual", "explicit",
    ],
    ContentRating.TEEN: [
        "fuck", "cunt", "explicit sexual", "graphic violence",
        "pornographic", "slur",
    ],
    ContentRating.ADULT: [
        "explicit sexual", "pornographic", "graphic penetration",
        "sustained explicit", "slur",
    ],
    ContentRating.MATURE: [
        "pornographic", "explicit penetration", "child sexual",
        "snuff", "slur",
    ],
}

# Platform hard floor — these trigger regardless of production rating
PLATFORM_HARD_FLOOR = [
    "child sexual", "snuff", "explicit penetration sustained",
    "pornographic sustained",
]


# ─────────────────────────────────────────────────────────────────────────────
# DISCLAIMER
# ─────────────────────────────────────────────────────────────────────────────

DISCLAIMER_VERSIONS: Dict[str, str] = {
    ContentRating.CHILDREN: (
        "This program is designed for young audiences. "
        "Content has been reviewed for age-appropriate material."
    ),
    ContentRating.FAMILY: (
        "This program contains content suitable for general audiences. "
        "Some material may not be appropriate for young children."
    ),
    ContentRating.TEEN: (
        "This is a live production. Content is rated TV-14 and may include "
        "mature themes, strong language, and adult situations. "
        "Viewer discretion is advised."
    ),
    ContentRating.ADULT: (
        "This is a live creative production. Content may include strong language, "
        "adult themes, and mature subject matter up to an R rating. "
        "This program is intended for adult audiences. "
        "We film everything — sometimes things get real. You've been warned."
    ),
    ContentRating.MATURE: (
        "This production contains mature adult content including strong language, "
        "explicit themes, and R-rated material. "
        "Intended for adult audiences only. "
        "This is a live production — content is unfiltered and unscripted. "
        "You've been warned."
    ),
}

@dataclass
class DisclaimerRecord:
    """Logged proof that the disclaimer was served."""
    disclaimer_id:  str
    session_id:     str
    content_rating: str
    disclaimer_text: str
    timestamp:      float
    broadcast_mode: str

    def to_db_dict(self) -> dict:
        return {
            "disclaimer_id":    self.disclaimer_id,
            "session_id":       self.session_id,
            "content_rating":   self.content_rating,
            "disclaimer_text":  self.disclaimer_text,
            "timestamp":        self.timestamp,
            "broadcast_mode":   self.broadcast_mode,
        }


# ─────────────────────────────────────────────────────────────────────────────
# CONDUCT TRACKING
# Three strikes — live broadcast only
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ConductRecord:
    """
    A single conduct request issued to a participant.
    Three of these ignored = escalate to director.
    """
    record_id:      str
    session_id:     str
    participant_id: str
    strike_number:  int         # 1, 2, or 3
    violation_type: str
    crew_member:    str         # Which crew member issued the request
    request_text:   str         # What was actually said
    timestamp:      float
    complied:       bool        = False
    compliance_timestamp: Optional[float] = None

    def to_db_dict(self) -> dict:
        return {
            "record_id":        self.record_id,
            "session_id":       self.session_id,
            "participant_id":   self.participant_id,
            "strike_number":    self.strike_number,
            "violation_type":   self.violation_type,
            "crew_member":      self.crew_member,
            "request_text":     self.request_text,
            "timestamp":        self.timestamp,
            "complied":         int(self.complied),
            "compliance_timestamp": self.compliance_timestamp,
        }


class ConductTracker:
    """
    Tracks conduct strikes per participant per session.
    Live broadcast only — recorded sessions don't use this.

    Three strikes without compliance = escalate to director.
    Compliance resets the count for that violation type.
    Violence = immediate escalation regardless of strike count.
    """

    def __init__(self, session_id: str, db_path: Path = DB_PATH):
        self.session_id = session_id
        self.db_path    = db_path
        # participant_id → list of ConductRecords this session
        self._strikes:  Dict[str, List[ConductRecord]] = {}

    def issue_request(
        self,
        participant_id: str,
        violation_type: str,
        crew_member:    str,
        request_text:   str,
    ) -> Tuple[ConductRecord, bool]:
        """
        Issue a conduct request to a participant.
        Returns (ConductRecord, should_escalate).
        should_escalate is True when this is the third ignored strike.
        Violence always escalates immediately.
        """
        # Violence is immediate regardless of strike count
        if violation_type == ConductViolationType.VIOLENCE:
            record = ConductRecord(
                record_id       = str(uuid.uuid4()),
                session_id      = self.session_id,
                participant_id  = participant_id,
                strike_number   = 99,   # Special — violence bypass
                violation_type  = violation_type,
                crew_member     = crew_member,
                request_text    = request_text,
                timestamp       = time.time(),
            )
            self._persist_record(record)
            logger.warning(f"[Conduct] VIOLENCE detected — immediate escalation")
            return record, True

        if participant_id not in self._strikes:
            self._strikes[participant_id] = []

        # Count active (uncomplied) strikes
        active_strikes = [
            r for r in self._strikes[participant_id]
            if not r.complied
        ]
        strike_number = len(active_strikes) + 1

        record = ConductRecord(
            record_id       = str(uuid.uuid4()),
            session_id      = self.session_id,
            participant_id  = participant_id,
            strike_number   = strike_number,
            violation_type  = violation_type,
            crew_member     = crew_member,
            request_text    = request_text,
            timestamp       = time.time(),
        )

        self._strikes[participant_id].append(record)
        self._persist_record(record)

        should_escalate = strike_number >= 3
        if should_escalate:
            logger.warning(
                f"[Conduct] Strike 3 for participant {participant_id} — escalating to director"
            )
        else:
            logger.info(
                f"[Conduct] Strike {strike_number} for participant {participant_id} "
                f"({violation_type})"
            )

        return record, should_escalate

    def record_compliance(self, participant_id: str) -> None:
        """Participant complied. Reset their active strikes."""
        if participant_id not in self._strikes:
            return
        now = time.time()
        for record in self._strikes[participant_id]:
            if not record.complied:
                record.complied = True
                record.compliance_timestamp = now
                self._persist_record(record)
        logger.info(f"[Conduct] Compliance recorded for {participant_id} — strikes reset")

    def get_strike_count(self, participant_id: str) -> int:
        """Active (uncomplied) strike count for a participant."""
        if participant_id not in self._strikes:
            return 0
        return len([r for r in self._strikes[participant_id] if not r.complied])

    def _persist_record(self, record: ConductRecord) -> None:
        with self._db() as conn:
            d = record.to_db_dict()
            conn.execute("""
                INSERT OR REPLACE INTO conduct_records
                    (record_id, session_id, participant_id, strike_number,
                     violation_type, crew_member, request_text, timestamp,
                     complied, compliance_timestamp)
                VALUES
                    (:record_id, :session_id, :participant_id, :strike_number,
                     :violation_type, :crew_member, :request_text, :timestamp,
                     :complied, :compliance_timestamp)
            """, d)

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"[Conduct] DB error: {e}")
            raise
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# DIRECTOR CHANNEL
# The production hierarchy communication layer
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DirectorSignal:
    """A signal sent up to or received from the director."""
    signal_id:      str
    direction:      str         # "to_director" | "from_director"
    command:        str         # DirectorCommand value
    reason:         str
    session_id:     str
    timestamp:      float
    participant_id: Optional[str] = None
    metadata:       Dict         = field(default_factory=dict)


class DirectorChannel:
    """
    The production hierarchy communication bus.

    Crew sends escalations UP to the director.
    Director sends commands DOWN to the crew.

    In a real integration this would be a WebSocket or event bus channel.
    Here it's a structured queue with persistence — the director can
    review what happened and when.
    """

    def __init__(self, session_id: str, db_path: Path = DB_PATH):
        self.session_id     = session_id
        self.db_path        = db_path
        self._outbound:     List[DirectorSignal] = []  # crew → director
        self._inbound:      List[DirectorSignal] = []  # director → crew
        self._callbacks:    List[Any]            = []  # registered listeners

    def escalate(
        self,
        command:        str,
        reason:         str,
        participant_id: Optional[str] = None,
        metadata:       Optional[Dict] = None,
    ) -> DirectorSignal:
        """
        Crew escalates to director.
        Used for: three strikes, violence detection, format breakdown.
        """
        signal = DirectorSignal(
            signal_id       = str(uuid.uuid4()),
            direction       = "to_director",
            command         = command,
            reason          = reason,
            session_id      = self.session_id,
            timestamp       = time.time(),
            participant_id  = participant_id,
            metadata        = metadata or {},
        )
        self._outbound.append(signal)
        self._persist_signal(signal)

        logger.warning(
            f"[Director] Escalation: {command} — {reason}"
            + (f" (participant: {participant_id})" if participant_id else "")
        )

        # Notify any registered listeners (e.g. live dashboard)
        for callback in self._callbacks:
            try:
                callback(signal)
            except Exception as e:
                logger.error(f"[Director] Callback error: {e}")

        return signal

    def receive_command(self, command: str, reason: str = "") -> DirectorSignal:
        """
        Director sends command to crew.
        Called when director issues a production command.
        """
        signal = DirectorSignal(
            signal_id   = str(uuid.uuid4()),
            direction   = "from_director",
            command     = command,
            reason      = reason,
            session_id  = self.session_id,
            timestamp   = time.time(),
        )
        self._inbound.append(signal)
        self._persist_signal(signal)
        logger.info(f"[Director] Command received: {command}")
        return signal

    def get_pending_commands(self) -> List[DirectorSignal]:
        """Get unprocessed commands from director."""
        return [s for s in self._inbound if s.direction == "from_director"]

    def register_callback(self, callback) -> None:
        """Register a listener for escalation events."""
        self._callbacks.append(callback)

    def _persist_signal(self, signal: DirectorSignal) -> None:
        with self._db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO director_signals
                    (signal_id, direction, command, reason, session_id,
                     timestamp, participant_id, metadata)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal.signal_id, signal.direction, signal.command,
                signal.reason, signal.session_id, signal.timestamp,
                signal.participant_id, json.dumps(signal.metadata),
            ))

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# CREW RESPONSE ENGINE
# Personality-agnostic. The same engine under Pete, Re-Pete, Sir Purflous.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CrewDirective:
    """
    What the crew should do in response to a signal.
    The directive is personality-agnostic — it describes the action,
    not the words. Each character executes it in their own voice.
    """
    directive_id:   str
    posture:        str             # ResponsePosture value
    urgency:        float           # 0.0 = background, 1.0 = immediate
    action:         str             # What to do
    suggested_text: Optional[str]  # Optional suggested language — crew can adapt
    channel:        str             # "live" | "earpiece" | "post_session" | "director"
    session_id:     str
    timestamp:      float           = field(default_factory=time.time)
    evidence_summary: str          = ""   # What triggered this


@dataclass
class CrewResponse:
    """
    The actual executed response — what the crew member said or did.
    Logged for post-session review.
    """
    response_id:    str
    directive_id:   str
    character:      str         # "pete" | "re_pete" | "sir_purflous"
    posture:        str
    text_delivered: str
    channel:        str
    session_id:     str
    timestamp:      float


# Response text templates — personality-agnostic suggestions.
# Each crew member adapts these to their own voice.
RESPONSE_TEMPLATES: Dict[str, Dict[str, List[str]]] = {
    ResponsePosture.C_HOLD: {
        "internal": [
            "Filed. Watching.",
            "Noted. Hold.",
        ],
    },
    ResponsePosture.STEER: {
        "suggested": [
            "That's interesting — let's come at it from this angle...",
            "I want to come back to that. Right now though...",
            "Hold that thought — there's something else here...",
        ],
    },
    ResponsePosture.ACKNOWLEDGE: {
        "suggested": [
            "Yeah.",
            "I hear that.",
            "Mm.",
        ],
    },
    ResponsePosture.BRIDGE_TO_BREAK: {
        "suggested": [
            "We're gonna take a quick break — back in two.",
            "Hold that thought. Quick break. Back shortly.",
            "Good place to pause — we'll be right back.",
        ],
    },
    ResponsePosture.ESCALATE: {
        "first_request": [
            "Hey — let's keep it together on set.",
            "Let's bring it down a notch.",
            "Watch the language please.",
        ],
        "second_request": [
            "I need you to bring it down. Now.",
            "Second time — let's get it together.",
            "Language. Seriously.",
        ],
        "third_request": [
            "That's three. We're going to break.",
            "Alright. Taking a break.",
        ],
    },
}


class CrewResponseEngine:
    """
    Evaluates incoming signals and decides what the crew does.

    DEFAULT IS ALWAYS C_HOLD.
    Every departure from C_HOLD requires justification.
    The engine is biased toward doing less, not more.

    Personality is applied at execution time, not evaluation time.
    The directive is the same for all crew members.
    The response text differs per character.
    """

    def __init__(
        self,
        session_config: "ProductionConfig",
        conduct_tracker: ConductTracker,
        director_channel: DirectorChannel,
    ):
        self.config         = session_config
        self.conduct        = conduct_tracker
        self.director       = director_channel
        self._responses:    List[CrewResponse] = []

    def evaluate(
        self,
        signal_type:        str,
        signal_intensity:   float           = 0.0,
        participant_id:     Optional[str]   = None,
        evidence_summary:   str             = "",
        violation_type:     Optional[str]   = None,
    ) -> CrewDirective:
        """
        Core evaluation loop.

        Takes a signal, returns a directive.
        Default is always C_HOLD.
        Only escalates when the signal justifies it AND the
        broadcast mode and content rating support it.
        """
        session_id = self.config.session_id

        # ── VIOLENCE — immediate hard cut regardless of mode ──────────────────
        if violation_type == ConductViolationType.VIOLENCE:
            self.director.escalate(
                command         = DirectorCommand.HARD_CUT,
                reason          = "Physical violence detected on set",
                participant_id  = participant_id,
            )
            return CrewDirective(
                directive_id    = str(uuid.uuid4()),
                posture         = ResponsePosture.HARD_CUT,
                urgency         = 1.0,
                action          = "Hard cut — director taking over",
                suggested_text  = None,
                channel         = "director",
                session_id      = session_id,
                evidence_summary = "Physical violence",
            )

        # ── RECORDED MODE — default C_HOLD, no escalation ────────────────────
        if self.config.broadcast_mode == BroadcastMode.RECORDED:
            # In recorded mode we only steer if signal is very high
            # and even then we never cut — we just guide gently
            if signal_intensity >= 0.85 and violation_type:
                return CrewDirective(
                    directive_id    = str(uuid.uuid4()),
                    posture         = ResponsePosture.STEER,
                    urgency         = 0.3,
                    action          = "Gentle steer — keep rolling",
                    suggested_text  = self._pick_template(ResponsePosture.STEER),
                    channel         = "earpiece",
                    session_id      = session_id,
                    evidence_summary = evidence_summary,
                )
            return self._c_hold(session_id, evidence_summary)

        # ── LIVE / REHEARSAL — full protocol active ───────────────────────────

        # Content rating violation check
        if violation_type and violation_type != ConductViolationType.VIOLENCE:
            strike_count = self.conduct.get_strike_count(participant_id or "unknown")

            if strike_count == 0:
                # First strike
                _, should_escalate = self.conduct.issue_request(
                    participant_id  = participant_id or "unknown",
                    violation_type  = violation_type,
                    crew_member     = "crew",
                    request_text    = self._pick_template(
                        ResponsePosture.ESCALATE, "first_request"
                    ),
                )
                return CrewDirective(
                    directive_id    = str(uuid.uuid4()),
                    posture         = ResponsePosture.ESCALATE,
                    urgency         = 0.7,
                    action          = "Issue first conduct request",
                    suggested_text  = self._pick_template(
                        ResponsePosture.ESCALATE, "first_request"
                    ),
                    channel         = "live",
                    session_id      = session_id,
                    evidence_summary = evidence_summary,
                )

            elif strike_count == 1:
                # Second strike
                self.conduct.issue_request(
                    participant_id  = participant_id or "unknown",
                    violation_type  = violation_type,
                    crew_member     = "crew",
                    request_text    = self._pick_template(
                        ResponsePosture.ESCALATE, "second_request"
                    ),
                )
                return CrewDirective(
                    directive_id    = str(uuid.uuid4()),
                    posture         = ResponsePosture.ESCALATE,
                    urgency         = 0.85,
                    action          = "Issue second conduct request — firm",
                    suggested_text  = self._pick_template(
                        ResponsePosture.ESCALATE, "second_request"
                    ),
                    channel         = "live",
                    session_id      = session_id,
                    evidence_summary = evidence_summary,
                )

            else:
                # Third strike — escalate to director
                _, _ = self.conduct.issue_request(
                    participant_id  = participant_id or "unknown",
                    violation_type  = violation_type,
                    crew_member     = "crew",
                    request_text    = self._pick_template(
                        ResponsePosture.ESCALATE, "third_request"
                    ),
                )
                self.director.escalate(
                    command         = DirectorCommand.CUT_TO_BREAK,
                    reason          = f"Three strikes — participant {participant_id}",
                    participant_id  = participant_id,
                )
                return CrewDirective(
                    directive_id    = str(uuid.uuid4()),
                    posture         = ResponsePosture.BRIDGE_TO_BREAK,
                    urgency         = 1.0,
                    action          = "Bridge to break — director cutting",
                    suggested_text  = self._pick_template(ResponsePosture.BRIDGE_TO_BREAK),
                    channel         = "live",
                    session_id      = session_id,
                    evidence_summary = evidence_summary,
                )

        # ── EMOTIONAL SIGNAL — default C_HOLD with optional steer ────────────
        # The emotional intelligence layer. This is where perception
        # becomes action — but the default is always to do less.

        if signal_intensity >= 0.80:
            # High intensity emotional signal — steer toward safer water
            return CrewDirective(
                directive_id    = str(uuid.uuid4()),
                posture         = ResponsePosture.STEER,
                urgency         = 0.4,
                action          = "Steer conversationally toward safer water",
                suggested_text  = self._pick_template(ResponsePosture.STEER),
                channel         = "earpiece",
                session_id      = session_id,
                evidence_summary = evidence_summary,
            )

        if signal_intensity >= 0.60:
            # Moderate signal — minimal acknowledgment if anything
            return CrewDirective(
                directive_id    = str(uuid.uuid4()),
                posture         = ResponsePosture.ACKNOWLEDGE,
                urgency         = 0.2,
                action          = "Minimal acknowledgment — tone only, keep moving",
                suggested_text  = self._pick_template(ResponsePosture.ACKNOWLEDGE),
                channel         = "earpiece",
                session_id      = session_id,
                evidence_summary = evidence_summary,
            )

        # Default — C_HOLD
        return self._c_hold(session_id, evidence_summary)

    def execute(
        self,
        directive:  CrewDirective,
        character:  str,
        actual_text: str = "",
    ) -> CrewResponse:
        """
        Log the crew's actual execution of a directive.
        actual_text is what the character actually said/did.
        """
        response = CrewResponse(
            response_id     = str(uuid.uuid4()),
            directive_id    = directive.directive_id,
            character       = character,
            posture         = directive.posture,
            text_delivered  = actual_text or directive.suggested_text or "",
            channel         = directive.channel,
            session_id      = directive.session_id,
            timestamp       = time.time(),
        )
        self._responses.append(response)
        return response

    def get_session_responses(self) -> List[CrewResponse]:
        return list(self._responses)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _c_hold(self, session_id: str, evidence_summary: str) -> CrewDirective:
        return CrewDirective(
            directive_id    = str(uuid.uuid4()),
            posture         = ResponsePosture.C_HOLD,
            urgency         = 0.0,
            action          = "Hold space. File it. Keep moving.",
            suggested_text  = None,
            channel         = "internal",
            session_id      = session_id,
            evidence_summary = evidence_summary,
        )

    def _pick_template(self, posture: str, sub_key: str = "suggested") -> str:
        """Pick a response template for a posture. Returns first option."""
        templates = RESPONSE_TEMPLATES.get(posture, {})
        options = templates.get(sub_key, templates.get("suggested", [""]))
        return options[0] if options else ""


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCTION CONFIG
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProductionConfig:
    """
    Per-session production configuration.
    Set by the producer before the session starts.
    """
    session_id:         str
    broadcast_mode:     str     = BroadcastMode.RECORDED
    content_rating:     str     = ContentRating.ADULT   # Platform default
    show_format:        str     = "talk_show"           # talk_show | comedy | interview | etc.
    has_live_director:  bool    = True
    participants:       List[str] = field(default_factory=list)
    notes:              str     = ""


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCTION SESSION
# The top-level orchestrator for a single session
# ─────────────────────────────────────────────────────────────────────────────

PRODUCTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS production_sessions (
    session_id      TEXT PRIMARY KEY,
    broadcast_mode  TEXT NOT NULL,
    content_rating  TEXT NOT NULL,
    show_format     TEXT NOT NULL,
    start_timestamp REAL NOT NULL,
    end_timestamp   REAL,
    notes           TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS disclaimer_records (
    disclaimer_id   TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    content_rating  TEXT NOT NULL,
    disclaimer_text TEXT NOT NULL,
    timestamp       REAL NOT NULL,
    broadcast_mode  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conduct_records (
    record_id           TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL,
    participant_id      TEXT NOT NULL,
    strike_number       INTEGER NOT NULL,
    violation_type      TEXT NOT NULL,
    crew_member         TEXT NOT NULL,
    request_text        TEXT NOT NULL,
    timestamp           REAL NOT NULL,
    complied            INTEGER DEFAULT 0,
    compliance_timestamp REAL
);

CREATE TABLE IF NOT EXISTS director_signals (
    signal_id       TEXT PRIMARY KEY,
    direction       TEXT NOT NULL,
    command         TEXT NOT NULL,
    reason          TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    timestamp       REAL NOT NULL,
    participant_id  TEXT,
    metadata        TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_conduct_session     ON conduct_records(session_id);
CREATE INDEX IF NOT EXISTS idx_conduct_participant ON conduct_records(participant_id);
CREATE INDEX IF NOT EXISTS idx_director_session    ON director_signals(session_id);
CREATE INDEX IF NOT EXISTS idx_disclaimer_session  ON disclaimer_records(session_id);
"""


class ProductionSession:
    """
    A single production session — broadcast or recorded.

    Orchestrates:
        - Disclaimer serving and logging
        - Broadcast mode and content rating
        - Conduct tracking
        - Director channel
        - Crew response engine
        - Session reporting

    Usage:
        config  = ProductionConfig(session_id="...", broadcast_mode=BroadcastMode.LIVE)
        session = ProductionSession(config)
        disclaimer = session.initialize()

        # During session:
        directive = session.process_signal(
            signal_type="emotional_undercurrent",
            signal_intensity=0.65,
            participant_id="guest_1",
        )

        # On violation:
        directive = session.process_signal(
            signal_type="conduct_violation",
            signal_intensity=1.0,
            participant_id="guest_1",
            violation_type=ConductViolationType.LANGUAGE,
        )

        # Director commands crew:
        session.director_channel.receive_command(DirectorCommand.CUT_TO_BREAK)

        # Session end:
        report = session.end_session()
    """

    def __init__(self, config: ProductionConfig, db_path: Path = DB_PATH):
        self.config     = config
        self.db_path    = db_path
        self._started   = False
        self._ended     = False

        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

        self.director_channel   = DirectorChannel(config.session_id, db_path)
        self.conduct_tracker    = ConductTracker(config.session_id, db_path)
        self.response_engine    = CrewResponseEngine(
            config, self.conduct_tracker, self.director_channel
        )

    def initialize(self) -> DisclaimerRecord:
        """
        Start the session. Serve and log the disclaimer.
        Must be called before process_signal().
        Returns the disclaimer record — show this to the audience.
        """
        disclaimer_text = DISCLAIMER_VERSIONS.get(
            self.config.content_rating,
            DISCLAIMER_VERSIONS[ContentRating.ADULT],
        )

        disclaimer = DisclaimerRecord(
            disclaimer_id   = str(uuid.uuid4()),
            session_id      = self.config.session_id,
            content_rating  = self.config.content_rating,
            disclaimer_text = disclaimer_text,
            timestamp       = time.time(),
            broadcast_mode  = self.config.broadcast_mode,
        )

        self._persist_disclaimer(disclaimer)
        self._persist_session()
        self._started = True

        logger.info(
            f"[Production] Session initialized — "
            f"mode={self.config.broadcast_mode} "
            f"rating={self.config.content_rating}"
        )

        return disclaimer

    def process_signal(
        self,
        signal_type:        str,
        signal_intensity:   float           = 0.0,
        participant_id:     Optional[str]   = None,
        evidence_summary:   str             = "",
        violation_type:     Optional[str]   = None,
    ) -> CrewDirective:
        """
        Primary ingestion point for signals from VDI, Evidence Layer,
        Jeremy Cricket, and conduct monitoring.

        Returns a CrewDirective — what the crew should do.
        Default is always C_HOLD.
        """
        if not self._started:
            raise RuntimeError("Session not initialized. Call initialize() first.")

        return self.response_engine.evaluate(
            signal_type         = signal_type,
            signal_intensity    = signal_intensity,
            participant_id      = participant_id,
            evidence_summary    = evidence_summary,
            violation_type      = violation_type,
        )

    def participant_complied(self, participant_id: str) -> None:
        """Record that a participant complied with a conduct request."""
        self.conduct_tracker.record_compliance(participant_id)

    def end_session(self) -> "SessionReport":
        """
        Close the session and generate a summary report.
        """
        self._ended = True
        self._update_session_end()

        responses   = self.response_engine.get_session_responses()
        escalations = self.director_channel._outbound
        strikes     = {
            pid: self.conduct_tracker.get_strike_count(pid)
            for pid in self.config.participants
        }

        report = SessionReport(
            session_id          = self.config.session_id,
            broadcast_mode      = self.config.broadcast_mode,
            content_rating      = self.config.content_rating,
            total_responses     = len(responses),
            escalation_count    = len(escalations),
            strike_summary      = strikes,
            hard_cuts           = sum(
                1 for s in escalations
                if s.command == DirectorCommand.HARD_CUT
            ),
            posture_breakdown   = self._posture_breakdown(responses),
        )

        logger.info(
            f"[Production] Session ended — "
            f"{report.total_responses} responses, "
            f"{report.escalation_count} escalations, "
            f"{report.hard_cuts} hard cuts"
        )

        return report

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _posture_breakdown(self, responses: List[CrewResponse]) -> Dict[str, int]:
        breakdown: Dict[str, int] = {}
        for r in responses:
            breakdown[r.posture] = breakdown.get(r.posture, 0) + 1
        return breakdown

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._db() as conn:
            conn.executescript(PRODUCTION_SCHEMA)

    def _persist_disclaimer(self, disclaimer: DisclaimerRecord) -> None:
        with self._db() as conn:
            d = disclaimer.to_db_dict()
            conn.execute("""
                INSERT OR REPLACE INTO disclaimer_records
                    (disclaimer_id, session_id, content_rating,
                     disclaimer_text, timestamp, broadcast_mode)
                VALUES
                    (:disclaimer_id, :session_id, :content_rating,
                     :disclaimer_text, :timestamp, :broadcast_mode)
            """, d)

    def _persist_session(self) -> None:
        with self._db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO production_sessions
                    (session_id, broadcast_mode, content_rating,
                     show_format, start_timestamp, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                self.config.session_id,
                self.config.broadcast_mode,
                self.config.content_rating,
                self.config.show_format,
                time.time(),
                self.config.notes,
            ))

    def _update_session_end(self) -> None:
        with self._db() as conn:
            conn.execute("""
                UPDATE production_sessions
                SET end_timestamp = ?
                WHERE session_id = ?
            """, (time.time(), self.config.session_id))


# ─────────────────────────────────────────────────────────────────────────────
# SESSION REPORT
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SessionReport:
    """Post-session summary. Fed into post-session reflection."""
    session_id:         str
    broadcast_mode:     str
    content_rating:     str
    total_responses:    int
    escalation_count:   int
    strike_summary:     Dict[str, int]
    hard_cuts:          int
    posture_breakdown:  Dict[str, int]

    def to_briefing(self) -> str:
        lines = [
            f"SESSION REPORT — {self.session_id}",
            f"Mode: {self.broadcast_mode} | Rating: {self.content_rating}",
            f"Responses: {self.total_responses} | Escalations: {self.escalation_count}",
        ]
        if self.hard_cuts:
            lines.append(f"HARD CUTS: {self.hard_cuts}")
        if any(v > 0 for v in self.strike_summary.values()):
            lines.append("Conduct:")
            for pid, strikes in self.strike_summary.items():
                if strikes > 0:
                    lines.append(f"  {pid}: {strikes} active strikes")
        if self.posture_breakdown:
            lines.append("Posture breakdown:")
            for posture, count in sorted(
                self.posture_breakdown.items(), key=lambda x: x[1], reverse=True
            ):
                lines.append(f"  {posture}: {count}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# FACTORY
# ─────────────────────────────────────────────────────────────────────────────

def create_production_session(
    session_id:     str,
    broadcast_mode: str     = BroadcastMode.RECORDED,
    content_rating: str     = ContentRating.ADULT,
    show_format:    str     = "talk_show",
    participants:   Optional[List[str]] = None,
    db_path:        Path    = DB_PATH,
) -> ProductionSession:
    """
    Factory. Creates and returns a ready ProductionSession.

    Call .initialize() on the returned session before use.

    Usage:
        session = create_production_session(
            session_id      = "show_001",
            broadcast_mode  = BroadcastMode.LIVE,
            content_rating  = ContentRating.ADULT,
            show_format     = "talk_show",
            participants    = ["host", "guest_1"],
        )
        disclaimer = session.initialize()
        # Show disclaimer to audience
        # Then run the show
    """
    config = ProductionConfig(
        session_id      = session_id,
        broadcast_mode  = broadcast_mode,
        content_rating  = content_rating,
        show_format     = show_format,
        participants    = participants or [],
    )
    return ProductionSession(config, db_path)
