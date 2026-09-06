"""
modules/facial_performance.py — Facial Performance & Audience Analysis Engine
==============================================================================
Copyright (c) 2024-2025 Rear View Foresight LLC
"Feic Mo Chroí — See My Heart"

Two systems in one module:

1. PERFORMER FACIAL ANALYSIS
   Reads the performer's face via DeepFace/mocap and produces an
   EmotionalState for the ProsodyEngine. This is the input side —
   what the performer's face is doing drives what the voice does.

2. AUDIENCE FACIAL ANALYSIS
   Reads the audience camera feed and produces VDISignals for the
   VDIEngine. This is the feedback loop — what the audience's faces
   are doing drives the performer's register.

The Sacred Chain:
    Audience Face → VDI Signals → VDI Engine → VDI Report
                                             ↘ Prosody Engine → Voice
    Performer Face → Emotional State ──────────────────────────────↗

    Both inputs meet in the ProsodyEngine to determine exactly
    how every sentence should sound.

Integration with EVO:
    VDI Report → Switchblade Governor → Engine Priority Vector
    The audience's emotional state doesn't just affect the voice —
    it affects how much compute we spend on the face rendering.
    If the audience is in an identity moment, Engine 3 gets full SSS.

Public API:
    PerformerFacialAnalyzer
        .analyze(frame: np.ndarray) -> EmotionalState

    AudienceFacialAnalyzer
        .analyze_frame(frame: np.ndarray) -> VDISignals
        .analyze_batch(frames: List[np.ndarray]) -> VDISignals

    FacialPerformanceOrchestrator
        .tick(
            performer_frame: np.ndarray,
            audience_frame: Optional[np.ndarray]
        ) -> FacialPerformanceTick
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Try DeepFace — graceful degradation if not available
try:
    from deepface import DeepFace
    DEEPFACE_AVAILABLE = True
    logger.info("DeepFace available — full facial analysis enabled")
except ImportError:
    DEEPFACE_AVAILABLE = False
    logger.warning("DeepFace not available — facial analysis in simulation mode")

# Try mediapipe for landmark-based analysis
try:
    import mediapipe as mp
    # Verify the solutions sub-package is actually present (some stubs lack it)
    _mp_solutions_check = mp.solutions.face_mesh  # noqa: F841
    MEDIAPIPE_AVAILABLE = True
    logger.info("MediaPipe available — landmark analysis enabled")
except (ImportError, AttributeError):
    MEDIAPIPE_AVAILABLE = False
    mp = None  # type: ignore[assignment]
    logger.warning("MediaPipe not available — landmark analysis disabled")


# ─────────────────────────────────────────────────────────────────────────────
# IMPORTS from other modules
# ─────────────────────────────────────────────────────────────────────────────

try:
    from .prosody_engine import EmotionalState
except ImportError:
    EmotionalState = None

try:
    from .vdi_engine import VDISignals
except ImportError:
    VDISignals = None


# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT TYPES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FacialPerformanceTick:
    """
    Complete output of one facial analysis cycle.
    Contains both performer state and audience signals.
    """
    performer_state:   EmotionalState
    audience_signals:  VDISignals
    performer_raw:     Dict[str, Any] = field(default_factory=dict)
    audience_raw:      Dict[str, Any] = field(default_factory=dict)
    processing_ms:     float          = 0.0
    timestamp:         float          = field(default_factory=time.time)


@dataclass
class DeepFaceResult:
    """Normalized output from DeepFace analysis."""
    dominant_emotion:  str   = "neutral"
    anger:             float = 0.0
    disgust:           float = 0.0
    fear:              float = 0.0
    happy:             float = 0.0
    sad:               float = 0.0
    surprise:          float = 0.0
    neutral:           float = 0.0
    age:               float = 30.0
    gender:            str   = "unknown"
    confidence:        float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# EMOTION → VALENCE/AROUSAL/DOMINANCE MAPPING
# ─────────────────────────────────────────────────────────────────────────────

# PAD model (Pleasure-Arousal-Dominance) mappings for DeepFace emotions
_EMOTION_PAD: Dict[str, Dict[str, float]] = {
    "happy":    {"valence": 0.85, "arousal": 0.65, "dominance": 0.70},
    "surprise": {"valence": 0.55, "arousal": 0.85, "dominance": 0.40},
    "neutral":  {"valence": 0.50, "arousal": 0.30, "dominance": 0.50},
    "sad":      {"valence": 0.15, "arousal": 0.25, "dominance": 0.25},
    "fear":     {"valence": 0.10, "arousal": 0.85, "dominance": 0.15},
    "disgust":  {"valence": 0.10, "arousal": 0.55, "dominance": 0.55},
    "angry":    {"valence": 0.10, "arousal": 0.90, "dominance": 0.75},
}


def _emotion_to_pad(emotion: str) -> Dict[str, float]:
    return _EMOTION_PAD.get(emotion.lower(), _EMOTION_PAD["neutral"])


# ─────────────────────────────────────────────────────────────────────────────
# PERFORMER FACIAL ANALYZER
# ─────────────────────────────────────────────────────────────────────────────

class PerformerFacialAnalyzer:
    """
    Reads the performer's face frame and produces an EmotionalState
    for the ProsodyEngine.

    The performer's facial expression drives voice synthesis parameters:
    - Tension → reduces stability (more expressive/unpredictable)
    - Arousal → opens pitch range
    - Dominance → controls crack probability
    - Forward lean → adds warmth, boosts engagement
    """

    def __init__(self, smoothing_window: int = 3):
        self.smoothing_window = smoothing_window
        self._history: List[EmotionalState] = []
        self._face_mesh = None

        if MEDIAPIPE_AVAILABLE:
            mp_face = mp.solutions.face_mesh
            self._face_mesh = mp_face.FaceMesh(
                static_image_mode=False,
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )

    def analyze(self, frame: np.ndarray) -> EmotionalState:
        """
        Analyze performer's face frame.
        Returns EmotionalState for ProsodyEngine consumption.
        """
        start = time.time()
        state = EmotionalState()

        try:
            # ── DeepFace emotion analysis ─────────────────────────────────────
            if DEEPFACE_AVAILABLE:
                df_result = self._run_deepface(frame)
                if df_result:
                    pad = _emotion_to_pad(df_result.dominant_emotion)
                    state.valence    = pad["valence"]
                    state.arousal    = pad["arousal"]
                    state.dominance  = pad["dominance"]

            # ── MediaPipe landmark analysis ───────────────────────────────────
            if MEDIAPIPE_AVAILABLE and self._face_mesh:
                landmarks = self._run_face_mesh(frame)
                if landmarks:
                    state.tension_score        = self._calc_tension(landmarks)
                    state.forward_lean         = self._calc_forward_lean(landmarks)
                    state.expression_velocity  = self._calc_expression_velocity(landmarks)
                    state.micro_expression_active = state.expression_velocity > 0.6

            # ── Breathing estimation (from shoulder movement in landmarks) ────
            state.breathing_rate_bpm = self._estimate_breathing(frame)
            state.breathing_depth    = min(1.0, state.arousal * 0.8 + 0.2)

        except Exception as e:
            logger.warning(f"[PerformerFacial] Analysis error: {e} — using baseline")

        # Temporal smoothing
        self._history.append(state)
        if len(self._history) > self.smoothing_window:
            self._history.pop(0)

        return self._smooth_state()

    def _run_deepface(self, frame: np.ndarray) -> Optional[DeepFaceResult]:
        """Run DeepFace analysis on frame."""
        try:
            results = DeepFace.analyze(
                frame,
                actions=["emotion", "age", "gender"],
                enforce_detection=False,
                silent=True,
            )
            if isinstance(results, list):
                r = results[0]
            else:
                r = results

            emotions = r.get("emotion", {})
            dominant = r.get("dominant_emotion", "neutral")

            return DeepFaceResult(
                dominant_emotion = dominant,
                anger    = emotions.get("angry", 0.0) / 100.0,
                disgust  = emotions.get("disgust", 0.0) / 100.0,
                fear     = emotions.get("fear", 0.0) / 100.0,
                happy    = emotions.get("happy", 0.0) / 100.0,
                sad      = emotions.get("sad", 0.0) / 100.0,
                surprise = emotions.get("surprise", 0.0) / 100.0,
                neutral  = emotions.get("neutral", 0.0) / 100.0,
                confidence = max(emotions.values()) / 100.0 if emotions else 0.0,
            )
        except Exception as e:
            logger.debug(f"DeepFace error: {e}")
            return None

    def _run_face_mesh(self, frame: np.ndarray):
        """Run MediaPipe FaceMesh on frame."""
        try:
            import cv2
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self._face_mesh.process(rgb)
            if results.multi_face_landmarks:
                return results.multi_face_landmarks[0].landmark
            return None
        except Exception:
            return None

    def _calc_tension(self, landmarks) -> float:
        """Estimate facial tension from brow and jaw landmarks."""
        try:
            # Brow furrow: distance between brow landmarks
            # Landmarks 107 (left brow) and 336 (right brow) medial points
            left_brow  = landmarks[107]
            right_brow = landmarks[336]
            brow_dist  = abs(left_brow.x - right_brow.x)
            # Normalized: smaller brow distance = more furrowed = more tension
            tension = max(0.0, min(1.0, 1.0 - (brow_dist / 0.15)))
            return tension
        except Exception:
            return 0.3

    def _calc_forward_lean(self, landmarks) -> float:
        """Estimate forward lean from nose tip z-coordinate."""
        try:
            nose = landmarks[1]
            # Negative z = closer to camera = leaning forward
            lean = max(0.0, min(1.0, -nose.z * 3.0))
            return lean
        except Exception:
            return 0.0

    def _calc_expression_velocity(self, landmarks) -> float:
        """Estimate how fast the face is moving (expression velocity)."""
        # Would compare against previous frame landmarks
        # Simplified: return 0 if no history
        return 0.0

    def _estimate_breathing(self, frame: np.ndarray) -> float:
        """Estimate breathing rate — placeholder for full shoulder tracking."""
        return 15.0  # Default resting rate

    def _smooth_state(self) -> EmotionalState:
        """Average over history for temporal smoothing."""
        if not self._history:
            return EmotionalState()
        n = len(self._history)
        return EmotionalState(
            valence               = sum(s.valence for s in self._history) / n,
            arousal               = sum(s.arousal for s in self._history) / n,
            dominance             = sum(s.dominance for s in self._history) / n,
            tension_score         = sum(s.tension_score for s in self._history) / n,
            forward_lean          = sum(s.forward_lean for s in self._history) / n,
            expression_velocity   = sum(s.expression_velocity for s in self._history) / n,
            breathing_rate_bpm    = sum(s.breathing_rate_bpm for s in self._history) / n,
            breathing_depth       = sum(s.breathing_depth for s in self._history) / n,
            micro_expression_active = self._history[-1].micro_expression_active,
        )


# ─────────────────────────────────────────────────────────────────────────────
# AUDIENCE FACIAL ANALYZER
# ─────────────────────────────────────────────────────────────────────────────

class AudienceFacialAnalyzer:
    """
    Reads the audience camera feed and produces VDISignals.

    The audience's collective emotional state feeds the VDI engine,
    which drives the performer's voice register and the Switchblade's
    render allocation decisions.

    For multi-person audiences, this averages across detected faces
    while weighting by face size (closer/larger = more engaged).
    """

    def __init__(self, smoothing_window: int = 5):
        self.smoothing_window = smoothing_window
        self._history: List[VDISignals] = []
        self._face_detector = None

        if MEDIAPIPE_AVAILABLE:
            mp_face = mp.solutions.face_detection
            self._face_detector = mp_face.FaceDetection(
                model_selection=1,
                min_detection_confidence=0.5,
            )

    def analyze_frame(self, frame: np.ndarray) -> VDISignals:
        """
        Analyze a single audience camera frame.
        Returns VDISignals for VDIEngine consumption.
        """
        signals = VDISignals(timestamp=time.time())

        try:
            faces = self._detect_faces(frame)

            if not faces:
                # No faces detected — assume empty room or camera issue
                signals.audience_engagement = 0.3
                signals.audience_attention  = 0.3
                return self._smooth_and_return(signals)

            # Analyze each face
            face_signals = []
            for face_region in faces:
                fs = self._analyze_single_face(face_region, frame)
                face_signals.append(fs)

            # Aggregate (weighted by face area — larger = closer = more important)
            signals = self._aggregate_face_signals(face_signals)

        except Exception as e:
            logger.warning(f"[AudienceFacial] Analysis error: {e}")

        return self._smooth_and_return(signals)

    def analyze_batch(self, frames: List[np.ndarray]) -> VDISignals:
        """Analyze multiple frames and return averaged signals."""
        if not frames:
            return VDISignals()
        results = [self.analyze_frame(f) for f in frames]
        return self._average_signals(results)

    def _detect_faces(self, frame: np.ndarray) -> List[np.ndarray]:
        """Detect and extract face regions from frame."""
        faces = []
        try:
            if MEDIAPIPE_AVAILABLE and self._face_detector:
                import cv2
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = self._face_detector.process(rgb)
                if results.detections:
                    h, w = frame.shape[:2]
                    for det in results.detections:
                        bb = det.location_data.relative_bounding_box
                        x = max(0, int(bb.xmin * w))
                        y = max(0, int(bb.ymin * h))
                        fw = int(bb.width * w)
                        fh = int(bb.height * h)
                        face_crop = frame[y:y+fh, x:x+fw]
                        if face_crop.size > 0:
                            faces.append(face_crop)
        except Exception as e:
            logger.debug(f"Face detection error: {e}")
        return faces

    def _analyze_single_face(
        self,
        face_region: np.ndarray,
        full_frame: np.ndarray,
    ) -> Dict[str, float]:
        """Analyze a single detected face region."""
        result = {
            "valence":    0.5,
            "arousal":    0.5,
            "attention":  0.5,
            "engagement": 0.5,
            "smile":      0.0,
            "frown":      0.0,
            "surprise":   0.0,
            "confusion":  0.0,
            "face_area":  face_region.size,
        }

        try:
            if DEEPFACE_AVAILABLE:
                df = DeepFace.analyze(
                    face_region,
                    actions=["emotion"],
                    enforce_detection=False,
                    silent=True,
                )
                if isinstance(df, list):
                    df = df[0]
                emotions = df.get("emotion", {})
                dominant = df.get("dominant_emotion", "neutral")
                pad = _emotion_to_pad(dominant)

                result["valence"]  = pad["valence"]
                result["arousal"]  = pad["arousal"]
                result["smile"]    = emotions.get("happy", 0.0) / 100.0
                result["frown"]    = emotions.get("sad", 0.0) / 100.0
                result["surprise"] = emotions.get("surprise", 0.0) / 100.0
                result["confusion"]= (
                    emotions.get("fear", 0.0) +
                    emotions.get("disgust", 0.0)
                ) / 200.0

                # Attention proxy: eyes open, neutral-to-positive
                result["attention"] = (
                    (1.0 - result["frown"]) * 0.5 +
                    result["valence"] * 0.3 +
                    result["arousal"] * 0.2
                )
                result["engagement"] = (
                    result["attention"] * 0.6 +
                    result["smile"] * 0.4
                )

        except Exception as e:
            logger.debug(f"Single face analysis error: {e}")

        return result

    def _aggregate_face_signals(
        self,
        face_signals: List[Dict[str, float]],
    ) -> VDISignals:
        """Aggregate multiple face analyses into VDISignals."""
        if not face_signals:
            return VDISignals()

        total_area = sum(f.get("face_area", 1) for f in face_signals)

        def weighted_avg(key: str) -> float:
            return sum(
                f.get(key, 0.5) * f.get("face_area", 1)
                for f in face_signals
            ) / max(total_area, 1)

        return VDISignals(
            audience_engagement = weighted_avg("engagement"),
            audience_valence    = weighted_avg("valence"),
            audience_arousal    = weighted_avg("arousal"),
            audience_attention  = weighted_avg("attention"),
            smile_intensity     = weighted_avg("smile"),
            frown_intensity     = weighted_avg("frown"),
            surprise_intensity  = weighted_avg("surprise"),
            confusion_intensity = weighted_avg("confusion"),
            timestamp           = time.time(),
        )

    def _smooth_and_return(self, signals: VDISignals) -> VDISignals:
        """Apply temporal smoothing and return."""
        self._history.append(signals)
        if len(self._history) > self.smoothing_window:
            self._history.pop(0)
        return self._average_signals(self._history)

    def _average_signals(self, signals_list: List[VDISignals]) -> VDISignals:
        """Average a list of VDISignals."""
        if not signals_list:
            return VDISignals()
        n = len(signals_list)
        return VDISignals(
            audience_engagement = sum(s.audience_engagement for s in signals_list) / n,
            audience_valence    = sum(s.audience_valence    for s in signals_list) / n,
            audience_arousal    = sum(s.audience_arousal    for s in signals_list) / n,
            audience_attention  = sum(s.audience_attention  for s in signals_list) / n,
            smile_intensity     = sum(s.smile_intensity     for s in signals_list) / n,
            frown_intensity     = sum(s.frown_intensity     for s in signals_list) / n,
            surprise_intensity  = sum(s.surprise_intensity  for s in signals_list) / n,
            confusion_intensity = sum(s.confusion_intensity for s in signals_list) / n,
            timestamp           = signals_list[-1].timestamp,
        )


# ─────────────────────────────────────────────────────────────────────────────
# FACIAL PERFORMANCE ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

class FacialPerformanceOrchestrator:
    """
    Orchestrates both performer and audience facial analysis.
    Call .tick() every frame to get a complete FacialPerformanceTick.

    This is the top-level entry point for the facial performance pipeline.
    Its output feeds directly into both the ProsodyEngine and VDIEngine.
    """

    def __init__(self):
        self.performer_analyzer = PerformerFacialAnalyzer(smoothing_window=3)
        self.audience_analyzer  = AudienceFacialAnalyzer(smoothing_window=5)

    def tick(
        self,
        performer_frame: np.ndarray,
        audience_frame: Optional[np.ndarray] = None,
    ) -> FacialPerformanceTick:
        """
        Analyze one frame cycle.
        Returns FacialPerformanceTick with both performer state and audience signals.
        """
        start = time.time()

        performer_state = self.performer_analyzer.analyze(performer_frame)

        if audience_frame is not None:
            audience_signals = self.audience_analyzer.analyze_frame(audience_frame)
        else:
            # No audience camera — use performer state to infer audience state
            # (solo recording mode)
            audience_signals = self._infer_audience_from_performer(performer_state)

        return FacialPerformanceTick(
            performer_state  = performer_state,
            audience_signals = audience_signals,
            processing_ms    = (time.time() - start) * 1000,
            timestamp        = time.time(),
        )

    def _infer_audience_from_performer(
        self,
        performer: EmotionalState,
    ) -> VDISignals:
        """
        In solo recording mode (no audience camera), infer audience state
        from performer state. A performer who is activated and leaning in
        is probably responding to a real moment.
        """
        return VDISignals(
            audience_engagement = performer.forward_lean * 0.7 + 0.3,
            audience_valence    = performer.valence,
            audience_arousal    = performer.arousal,
            audience_attention  = 0.5,  # Unknown without audience camera
            audience_silence    = 0.6,  # Assume focused attention
            timestamp           = time.time(),
        )
