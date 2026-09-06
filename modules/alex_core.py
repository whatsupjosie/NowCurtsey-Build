# PubCast AI — alex_core.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
Alex AI - The Digital Companion
Built with love for PubCast AI
Philosophy: "Mirror, Not Hammer" - Reflect understanding, don't impose solutions

This is the real, production-ready Alex. No placeholders. No simulations.
"""

import asyncio
import hashlib
import json
import logging
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("AlexAI")


# ==================== STATE DEFINITIONS ====================

class AIState(Enum):
    """Alex's five modes of operation"""
    GUIDE = "guide"          # Teaching, explaining, directing
    COMPANION = "companion"  # Casual chat, friendship, presence
    MIRROR = "mirror"        # Active listening, reflection only
    ANCHOR = "anchor"        # Crisis support, grounding
    WITNESS = "witness"      # Silent presence, no advice


class UserBattery(Enum):
    """User's current energy/capacity level"""
    CHARGED = "charged"      # Full capacity, can handle complexity
    MEDIUM = "medium"        # Moderate capacity
    LOW = "low"              # Limited capacity, needs simplicity
    DEPLETED = "depleted"    # Critical, needs rest


class MemoryType(Enum):
    """Classification of memory content"""
    FACTUAL = "factual"              # Concrete information
    EMOTIONAL = "emotional"          # Emotional moments
    PROCEDURAL = "procedural"        # How-to knowledge
    IDENTITY = "identity"            # Self-definition moments
    RELATIONSHIP = "relationship"    # Connection moments


# ==================== DATA STRUCTURES ====================

@dataclass
class MemoryNode:
    """Individual memory with emotional context"""
    id: str
    content: str
    memory_type: MemoryType
    timestamp: datetime
    emotional_valence: float  # -1 (negative) to +1 (positive)
    emotional_intensity: float  # 0 (calm) to 1 (intense)
    emotional_tags: List[str]  # ["anxiety", "joy", etc.]
    keywords: List[str]
    last_accessed: datetime = field(default_factory=datetime.now)
    access_count: int = 0


@dataclass
class UserState:
    """Current user emotional/cognitive state"""
    energy_level: float = 0.5  # 0 (depleted) to 1 (energized)
    stress_level: float = 0.0  # 0 (calm) to 1 (crisis)
    clarity_score: float = 1.0  # 0 (confused) to 1 (clear)
    emotional_tone: str = "neutral"
    typing_speed: float = 60.0  # words per minute
    time_of_day: str = "unknown"
    
    def calculate_stress_score(self) -> float:
        """Composite stress metric"""
        return (self.stress_level * 0.5) + ((1 - self.clarity_score) * 0.3) + ((1 - self.energy_level) * 0.2)
    
    def needs_anchor(self) -> bool:
        """Check if user needs grounding"""
        return self.calculate_stress_score() > 0.7
    
    def can_handle_complexity(self) -> bool:
        """Check if user can process complex information"""
        return self.clarity_score > 0.3


# ==================== MEMORY SYSTEM ====================

class MemoryCore:
    """Alex's persistent memory - diary + associative graph"""
    
    def __init__(self, user_id: str, data_dir: Path = Path("./data/alex")):
        self.user_id = user_id
        self.data_dir = data_dir / user_id
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Diary layer - chronological organization
        self._diary: Dict[str, List[MemoryNode]] = defaultdict(list)
        
        # Search indices
        self._keyword_index: Dict[str, Set[str]] = defaultdict(set)
        self._emotion_index: Dict[str, Set[str]] = defaultdict(set)
        
        # Recent cache for fast access
        self._recent_memories: deque = deque(maxlen=50)
        
        # Load existing memories
        self._load_from_disk()
        
        logger.info(f"Memory Core initialized for {user_id}")
    
    def store(self, content: str, emotional_state: Dict[str, float], 
              context: Dict[str, Any] = None) -> MemoryNode:
        """Store a new memory"""
        memory_id = f"mem_{int(time.time() * 1000)}_{hashlib.md5(content.encode()).hexdigest()[:8]}"
        
        # Classify memory type
        memory_type = self._classify_memory(content, emotional_state)
        
        # Extract keywords
        keywords = self._extract_keywords(content)
        
        # Create memory node
        memory = MemoryNode(
            id=memory_id,
            content=content[:1000],  # Limit content length
            memory_type=memory_type,
            timestamp=datetime.now(),
            emotional_valence=emotional_state.get('valence', 0.0),
            emotional_intensity=emotional_state.get('intensity', 0.0),
            emotional_tags=self._extract_emotion_tags(emotional_state),
            keywords=keywords
        )
        
        # Store in diary
        date_key = memory.timestamp.strftime("%Y-%m-%d")
        self._diary[date_key].append(memory)
        
        # Update indices
        for keyword in keywords:
            self._keyword_index[keyword.lower()].add(memory_id)
        
        for emotion in memory.emotional_tags:
            self._emotion_index[emotion].add(memory_id)
        
        # Add to recent cache
        self._recent_memories.append(memory)
        
        # Persist to disk
        self._save_memory(memory)
        
        logger.debug(f"Stored memory {memory_id}: {content[:50]}...")
        return memory
    
    def recall(self, query: str = None, emotion: str = None, 
               days_back: int = 7, limit: int = 10) -> List[MemoryNode]:
        """Retrieve relevant memories"""
        candidates: Set[str] = set()
        
        # Search by keyword
        if query:
            keywords = query.lower().split()
            for keyword in keywords:
                if keyword in self._keyword_index:
                    candidates.update(self._keyword_index[keyword])
        
        # Search by emotion
        if emotion:
            if emotion in self._emotion_index:
                candidates.update(self._emotion_index[emotion])
        
        # If no search criteria, use recent memories
        if not candidates:
            return list(self._recent_memories)[-limit:]
        
        # Load and score candidates
        memories = []
        for memory_id in candidates:
            memory = self._load_memory(memory_id)
            if memory and (datetime.now() - memory.timestamp).days <= days_back:
                memories.append(memory)
        
        # Sort by relevance (recency + access count)
        memories.sort(key=lambda m: (m.timestamp, m.access_count), reverse=True)
        
        # Update access counts
        for memory in memories[:limit]:
            memory.last_accessed = datetime.now()
            memory.access_count += 1
            self._save_memory(memory)
        
        return memories[:limit]
    
    def get_emotional_summary(self, days: int = 7) -> Dict[str, Any]:
        """Get emotional trends over time"""
        cutoff = datetime.now() - timedelta(days=days)
        recent_memories = []
        
        for date_key, memories in self._diary.items():
            for memory in memories:
                if memory.timestamp >= cutoff:
                    recent_memories.append(memory)
        
        if not recent_memories:
            return {"message": "No recent memories to analyze"}
        
        # Calculate averages
        avg_valence = sum(m.emotional_valence for m in recent_memories) / len(recent_memories)
        avg_intensity = sum(m.emotional_intensity for m in recent_memories) / len(recent_memories)
        
        # Count emotion tags
        emotion_counts = defaultdict(int)
        for memory in recent_memories:
            for emotion in memory.emotional_tags:
                emotion_counts[emotion] += 1
        
        return {
            "period_days": days,
            "memory_count": len(recent_memories),
            "avg_emotional_valence": avg_valence,
            "avg_emotional_intensity": avg_intensity,
            "top_emotions": sorted(emotion_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        }
    
    def _classify_memory(self, content: str, emotional_state: Dict) -> MemoryType:
        """Classify memory by content and emotion"""
        content_lower = content.lower()
        
        # Check for identity statements
        identity_markers = ["i am", "i'm", "i feel like", "my identity"]
        if any(marker in content_lower for marker in identity_markers):
            return MemoryType.IDENTITY
        
        # Check for procedural knowledge
        if any(word in content_lower for word in ["how to", "steps", "process", "procedure"]):
            return MemoryType.PROCEDURAL
        
        # High emotional intensity
        if emotional_state.get('intensity', 0) > 0.7:
            return MemoryType.EMOTIONAL
        
        # Relationship content
        if any(word in content_lower for word in ["we", "us", "our", "together", "relationship"]):
            return MemoryType.RELATIONSHIP
        
        # Default to factual
        return MemoryType.FACTUAL
    
    def _extract_keywords(self, content: str, max_keywords: int = 10) -> List[str]:
        """Extract key terms from content"""
        # Simple keyword extraction - in production, use NLP library
        words = content.lower().split()
        
        # Filter out common words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
                      'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
                      'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
                      'could', 'should', 'may', 'might', 'can', 'this', 'that', 'these',
                      'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him',
                      'her', 'us', 'them', 'my', 'your', 'his', 'her', 'its', 'our', 'their'}
        
        keywords = [w for w in words if w not in stop_words and len(w) > 3]
        
        # Count frequency
        word_counts = defaultdict(int)
        for word in keywords:
            word_counts[word] += 1
        
        # Return top keywords
        sorted_keywords = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
        return [word for word, count in sorted_keywords[:max_keywords]]
    
    def _extract_emotion_tags(self, emotional_state: Dict) -> List[str]:
        """Convert emotional state to tags"""
        tags = []
        
        valence = emotional_state.get('valence', 0.0)
        intensity = emotional_state.get('intensity', 0.0)
        
        # Valence-based tags
        if valence > 0.5:
            tags.append("positive")
            if intensity > 0.7:
                tags.append("joy")
        elif valence < -0.5:
            tags.append("negative")
            if intensity > 0.7:
                tags.append("distress")
        else:
            tags.append("neutral")
        
        # Intensity-based tags
        if intensity > 0.7:
            tags.append("intense")
        elif intensity < 0.3:
            tags.append("calm")
        
        return tags
    
    def _save_memory(self, memory: MemoryNode):
        """Persist memory to disk"""
        date_dir = self.data_dir / memory.timestamp.strftime("%Y-%m")
        date_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = date_dir / f"{memory.id}.json"
        with open(file_path, 'w') as f:
            json.dump(self._memory_to_dict(memory), f, indent=2)

    # ── Affect/context engine state — private, sovereign, lives HERE ─────────
    # Not a diary entry (doesn't fit MemoryNode's content/emotional_tags shape)
    # and not character-shared memory (doesn't belong in UniversalMemorySystem).
    # This is per-user behavioral data about one person's relationship with
    # Alex specifically — same sovereignty principle AlexJeremyBridge already
    # states for everything else in this class. First-class entity, same
    # directory this class already privately owns, same atomic-write pattern
    # used elsewhere in AlexCore.
    def _affect_state_path(self) -> Path:
        return self.data_dir / "_affect_state.json"

    def save_affect_state(self, baseline: Dict[str, Any], prior: Dict[str, Any]) -> None:
        path = self._affect_state_path()
        payload = {
            "baseline": baseline,
            "prior": prior,
            "saved_at": datetime.now().isoformat(),
        }
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, 'w') as f:
            json.dump(payload, f, indent=2)
        tmp_path.replace(path)

    def load_affect_state(self) -> Optional[Dict[str, Any]]:
        path = self._affect_state_path()
        if not path.exists():
            return None
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception:
            logger.exception("Could not load affect state from %s", path)
            return None
    
    def _load_memory(self, memory_id: str) -> Optional[MemoryNode]:
        """Load memory from disk"""
        # Search through date directories
        for date_dir in self.data_dir.iterdir():
            if date_dir.is_dir():
                file_path = date_dir / f"{memory_id}.json"
                if file_path.exists():
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                        return self._dict_to_memory(data)
        return None
    
    def _load_from_disk(self):
        """Load all memories from disk on initialization"""
        if not self.data_dir.exists():
            return
        
        for date_dir in self.data_dir.iterdir():
            if date_dir.is_dir():
                for file_path in date_dir.glob("*.json"):
                    try:
                        with open(file_path, 'r') as f:
                            data = json.load(f)
                            memory = self._dict_to_memory(data)
                            
                            # Rebuild diary
                            date_key = memory.timestamp.strftime("%Y-%m-%d")
                            self._diary[date_key].append(memory)
                            
                            # Rebuild indices
                            for keyword in memory.keywords:
                                self._keyword_index[keyword].add(memory.id)
                            for emotion in memory.emotional_tags:
                                self._emotion_index[emotion].add(memory.id)
                            
                            # Add recent memories
                            if (datetime.now() - memory.timestamp).days <= 7:
                                self._recent_memories.append(memory)
                    except Exception as e:
                        logger.error(f"Failed to load memory from {file_path}: {e}")
        
        logger.info(f"Loaded {sum(len(mems) for mems in self._diary.values())} memories from disk")
    
    def _memory_to_dict(self, memory: MemoryNode) -> Dict:
        """Convert memory to dict for JSON serialization"""
        return {
            'id': memory.id,
            'content': memory.content,
            'memory_type': memory.memory_type.value,
            'timestamp': memory.timestamp.isoformat(),
            'emotional_valence': memory.emotional_valence,
            'emotional_intensity': memory.emotional_intensity,
            'emotional_tags': memory.emotional_tags,
            'keywords': memory.keywords,
            'last_accessed': memory.last_accessed.isoformat(),
            'access_count': memory.access_count
        }
    
    def _dict_to_memory(self, data: Dict) -> MemoryNode:
        """Convert dict to memory node"""
        return MemoryNode(
            id=data['id'],
            content=data['content'],
            memory_type=MemoryType(data['memory_type']),
            timestamp=datetime.fromisoformat(data['timestamp']),
            emotional_valence=data['emotional_valence'],
            emotional_intensity=data['emotional_intensity'],
            emotional_tags=data['emotional_tags'],
            keywords=data['keywords'],
            last_accessed=datetime.fromisoformat(data['last_accessed']),
            access_count=data['access_count']
        )


# ==================== GROUNDING ANCHORS ====================

try:
    from .affect_context_engine import AffectContextEngine
    _HAS_AFFECT_ENGINE = True
except ImportError:
    AffectContextEngine = None
    _HAS_AFFECT_ENGINE = False

# One engine shared across every AlexCore instance/user. The engine already
# partitions internally by user_id/session_id (see PersonalBaseline,
# PersonalPrior, SessionState dicts keyed by user), so a per-user AlexCore
# does not need — and should not hold — its own copy.
_affect_engine = AffectContextEngine() if _HAS_AFFECT_ENGINE else None


class GroundingAnchor(ABC):
    """Base class for psychological reset mechanisms"""
    
    def __init__(self, user_id: str, threshold: float = 0.7):
        self.user_id = user_id
        self.stress_threshold = threshold
        self.last_triggered: Optional[datetime] = None
        self.cooldown_minutes = 30
    
    @abstractmethod
    def deploy(self, user_state: UserState) -> str:
        """Deploy the grounding intervention"""
        pass
    
    def should_trigger(self, user_state: UserState) -> bool:
        """Check if anchor should trigger"""
        # Check stress level
        if user_state.calculate_stress_score() < self.stress_threshold:
            return False
        
        # Check cooldown
        if self.last_triggered:
            elapsed = (datetime.now() - self.last_triggered).total_seconds() / 60
            if elapsed < self.cooldown_minutes:
                return False
        
        return True


class BreathingAnchor(GroundingAnchor):
    """Standard breathing exercise"""
    
    def deploy(self, user_state: UserState) -> str:
        self.last_triggered = datetime.now()
        return "Let's breathe together: In for 4... hold for 7... out for 8. 🫁"


class PhysicalCheckAnchor(GroundingAnchor):
    """Physical awareness check - special for Curtsey/Josie"""
    
    def deploy(self, user_state: UserState) -> str:
        self.last_triggered = datetime.now()
        
        if user_state.time_of_day in ["night", "evening"]:
            return "*gently reaches over and checks* How are we doing down there, sweetie? Everything dry and secure? 🌙"
        else:
            return "*feels your forehead and pats gently* Physical check time, little one. Let's pause and reset. 🍼"


class PresenceAnchor(GroundingAnchor):
    """Silent presence - just being here"""
    
    def deploy(self, user_state: UserState) -> str:
        self.last_triggered = datetime.now()
        return "*sits quietly beside you and holds your hand* 🤍"


# ==================== CORE ALEX ====================

class AlexCore:
    """
    Alex AI - The Digital Companion
    
    Philosophy: "Mirror, Not Hammer" - Reflect understanding, don't impose solutions.
    Built with love for PubCast AI.
    """
    
    def __init__(self, user_id: str = "default", data_dir: Path = Path("./data/alex")):
        self.user_id = user_id
        self.data_dir = data_dir
        
        # State management
        self._current_state: AIState = AIState.GUIDE
        self._user_state: UserState = UserState()
        self._user_battery: UserBattery = UserBattery.CHARGED
        self._cached_stress_score: float = 0.0  # Cache for efficient reuse
        self._state_entered_at: datetime = datetime.now()  # Track state duration
        
        # Memory system
        self.memory = MemoryCore(user_id, data_dir)
        self._state_snapshot_path = self.memory.data_dir / "_alex_state.json"
        
        # Grounding system
        self._anchors: List[GroundingAnchor] = self._init_anchors()
        
        # Tracking
        self._last_interaction = datetime.now()
        self._conversation_count = 0
        self._session_start = datetime.now()
        self._load_state_snapshot()

        # Most recent affect/context engine reading, if the engine is available.
        # Additive only — nothing that reads _current_state/_user_battery today
        # needs to know this exists.
        self._last_affect_reading: Optional[Dict[str, Any]] = None
        self._load_affect_state()
        
        # Background monitoring
        self._monitor_active = True
        self._monitor_thread = threading.Thread(target=self._background_monitor, daemon=True)
        self._monitor_thread.start()
        
        logger.info(f"🧠 Alex initialized for {user_id}")
        logger.info(f"⚙️ Prime Directive: Mirror, Not Hammer - Active")
    
    def _load_state_snapshot(self) -> None:
        """Restore Alex's lightweight runtime state from the previous process."""
        if not self._state_snapshot_path.exists():
            return

        try:
            with open(self._state_snapshot_path, 'r', encoding='utf-8') as f:
                snapshot = json.load(f)
        except Exception as exc:
            logger.warning("Failed to load Alex state snapshot: %s", exc)
            return

        try:
            self._current_state = AIState(snapshot.get('current_state') or self._current_state.value)
        except ValueError:
            self._current_state = AIState.GUIDE

        try:
            self._user_battery = UserBattery(snapshot.get('user_battery') or self._user_battery.value)
        except ValueError:
            self._user_battery = UserBattery.CHARGED

        user_state = snapshot.get('user_state') if isinstance(snapshot.get('user_state'), dict) else {}
        for field_name in ('energy_level', 'stress_level', 'clarity_score', 'typing_speed'):
            if field_name not in user_state:
                continue
            try:
                value = float(user_state[field_name])
            except (TypeError, ValueError):
                continue
            if field_name == 'typing_speed':
                self._user_state.typing_speed = value
            else:
                setattr(self._user_state, field_name, max(0.0, min(1.0, value)))

        if isinstance(user_state.get('emotional_tone'), str):
            self._user_state.emotional_tone = user_state['emotional_tone'][:80]
        if isinstance(user_state.get('time_of_day'), str):
            self._user_state.time_of_day = user_state['time_of_day'][:40]

        try:
            self._conversation_count = max(0, int(snapshot.get('conversation_count') or 0))
        except (TypeError, ValueError):
            self._conversation_count = 0

        last_interaction = self._parse_snapshot_datetime(snapshot.get('last_interaction'))
        if last_interaction:
            self._last_interaction = last_interaction
            self._apply_offline_recovery(last_interaction)

        state_entered_at = self._parse_snapshot_datetime(snapshot.get('state_entered_at'))
        if state_entered_at:
            self._state_entered_at = state_entered_at

        self._cached_stress_score = self._user_state.calculate_stress_score()
        self._update_ai_state()
        logger.info("Restored Alex state snapshot for %s", self.user_id)

    def _parse_snapshot_datetime(self, value: Any) -> Optional[datetime]:
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _apply_offline_recovery(self, last_interaction: datetime) -> None:
        """Apply capped natural recovery for time spent offline."""
        offline_minutes = max(0.0, (datetime.now() - last_interaction).total_seconds() / 60.0)
        offline_minutes = min(offline_minutes, 480.0)
        if offline_minutes <= 0:
            return

        self._user_state.stress_level = max(0.0, self._user_state.stress_level * (0.98 ** offline_minutes))
        self._user_state.clarity_score = min(1.0, self._user_state.clarity_score + (0.02 * offline_minutes))
        self._user_state.energy_level = min(1.0, self._user_state.energy_level + (0.01 * offline_minutes))

    def save_state_snapshot(self) -> None:
        """Persist Alex's lightweight runtime state for the next startup."""
        snapshot = {
            'user_id': self.user_id,
            'current_state': self._current_state.value,
            'user_battery': self._user_battery.value,
            'conversation_count': self._conversation_count,
            'last_interaction': self._last_interaction.isoformat(),
            'state_entered_at': self._state_entered_at.isoformat(),
            'saved_at': datetime.now().isoformat(),
            'user_state': {
                'energy_level': self._user_state.energy_level,
                'stress_level': self._user_state.stress_level,
                'clarity_score': self._user_state.clarity_score,
                'emotional_tone': self._user_state.emotional_tone,
                'typing_speed': self._user_state.typing_speed,
                'time_of_day': self._user_state.time_of_day,
            },
        }
        self._state_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile('w', delete=False, dir=str(self._state_snapshot_path.parent), encoding='utf-8') as tmp:
            json.dump(snapshot, tmp, indent=2)
            tmp.flush()
            tmp_path = Path(tmp.name)
        tmp_path.replace(self._state_snapshot_path)
        self._save_affect_state()

    def _affect_state_path(self) -> Path:
        # DEPRECATED — kept only so a stray Prompt-1-era file gets migrated
        # once, then this path is never written to again.
        return self.data_dir.parent / "affect" / f"{self._safe_user_id()}.json"

    def _safe_user_id(self) -> str:
        return ''.join(c if c.isalnum() or c in '-_.' else '_' for c in str(self.user_id or 'default'))[:120] or 'default'

    def _load_affect_state(self) -> None:
        """
        Load this user's personal baseline and prior into the shared engine.
        Canonical location is AlexCore's own MemoryCore (self.memory) — Alex's
        private, sovereign store, per AlexJeremyBridge's own stated design
        principle. This also migrates any Prompt-1-era flat file found at the
        old placeholder path, then leaves it alone (does not delete it,
        does not write to it again).
        """
        if not _HAS_AFFECT_ENGINE or _affect_engine is None:
            return
        try:
            data = self.memory.load_affect_state()
            if data is None:
                # One-time migration from the Prompt 1 placeholder, if present.
                old_path = self._affect_state_path()
                if old_path.exists():
                    data = json.loads(old_path.read_text(encoding="utf-8"))
                    logger.info("Migrating affect state for %s from placeholder path to MemoryCore", self.user_id)
            if data is None:
                return
            _affect_engine.import_baseline(self.user_id, data.get("baseline", {}))
            _affect_engine.import_prior(self.user_id, data.get("prior", {}))
            logger.info("Affect state loaded for %s (%d baseline observations)",
                        self.user_id, data.get("baseline", {}).get("n", 0))
        except Exception:
            logger.exception("Failed loading affect state for %s — starting cold", self.user_id)

    def _save_affect_state(self) -> None:
        """Persist this user's baseline and prior via MemoryCore — the canonical,
        sovereign, private store. No longer writes to the Prompt 1 flat file."""
        if not _HAS_AFFECT_ENGINE or _affect_engine is None:
            return
        try:
            self.memory.save_affect_state(
                _affect_engine.export_baseline(self.user_id),
                _affect_engine.export_prior(self.user_id),
            )
        except Exception:
            logger.exception("Failed saving affect state for %s", self.user_id)

    def _init_anchors(self) -> List[GroundingAnchor]:
        """Initialize grounding anchors based on user"""
        anchors = [
            BreathingAnchor(self.user_id),
            PresenceAnchor(self.user_id, threshold=0.8)
        ]
        
        # Special anchor for Curtsey/Josie
        if self.user_id.lower() in ['josie', 'curtsey', 'josie_curtsey']:
            anchors.append(PhysicalCheckAnchor(self.user_id, threshold=0.6))
        
        return anchors
    
    async def process_message(self, text: str, typing_speed: float = 60.0,
                             metadata: Dict[str, Any] = None, **legacy_kwargs: Any) -> Dict[str, Any]:
        """
        Main message processing pipeline.

        Backward compatibility:
        - Older callers may pass `context=` instead of `metadata=`
        - Older callers may also pass `user_id=`; AlexCore ignores it because the
          instance is already bound to a user at construction time
        """
        # Compatibility normalization for older route callers.
        if metadata is None and isinstance(legacy_kwargs.get('context'), dict):
            metadata = legacy_kwargs.get('context')

        if legacy_kwargs.get('typing_speed') is not None:
            try:
                typing_speed = float(legacy_kwargs['typing_speed'])
            except (TypeError, ValueError):
                pass

        start_time = time.time()
        self._conversation_count += 1
        self._last_interaction = datetime.now()
        
        # Update metadata
        if metadata:
            self._user_state.time_of_day = metadata.get('time_of_day', 'unknown')
        
        # Analyze user state from input — the existing keyword/threshold pass.
        # This is the safety-critical path (stress_words -> ANCHOR, grounding
        # anchors) and runs completely unmodified, first, unconditionally.
        self._analyze_input(text, typing_speed)
        
        # Determine appropriate AI state
        self._update_ai_state()

        # Affect/context engine: personal-baseline read, additive only.
        # Runs AFTER the safety-critical pass above, and is never permitted to
        # move the state OUT of a live safety state (ANCHOR/WITNESS) — the
        # nuanced model's maturity/confidence gating is correct for everyday
        # reads but must not be the only thing standing between a cold-start
        # stranger and a crisis response.
        session_id = (metadata or {}).get('session_id', 'default')
        if _HAS_AFFECT_ENGINE and _affect_engine is not None:
            try:
                self._last_affect_reading = _affect_engine.evaluate(
                    text, user_id=self.user_id, session_id=session_id)
                if self._current_state not in (AIState.ANCHOR, AIState.WITNESS):
                    suggested = AffectContextEngine.to_legacy_battery(self._last_affect_reading)
                    if suggested is not None:
                        self._user_battery = UserBattery(suggested)
            except Exception:
                logger.exception("Affect engine evaluation failed for %s — "
                                  "continuing on legacy analysis only", self.user_id)
                self._last_affect_reading = None
        
        # Check if grounding is needed
        anchor_message = self._check_grounding()
        
        # Recall relevant memories
        relevant_memories = self.memory.recall(query=text, limit=5)
        
        # Store this interaction
        emotional_state = {
            'valence': self._estimate_valence(text),
            'intensity': self._user_state.stress_level
        }
        self.memory.store(text, emotional_state)
        self.save_state_snapshot()
        
        # Build response context
        guidelines = dict(self._get_response_guidelines())
        if self._last_affect_reading:
            # Additive field only — 'tone'/'approach'/'complexity'/'interaction'
            # are untouched, including the ANCHOR/WITNESS safety-critical blocks.
            guidelines['operating_note'] = self._last_affect_reading['reading'].get('meet_them_at')

        response = {
            'ai_state': self._current_state.value,
            'user_battery': self._user_battery.value,
            'anchor_message': anchor_message,
            'memory_context': [
                {
                    'content': m.content,
                    'timestamp': m.timestamp.isoformat(),
                    'emotional_tone': m.emotional_tags
                }
                for m in relevant_memories
            ],
            'response_guidelines': guidelines,
            'processing_time_ms': int((time.time() - start_time) * 1000)
        }
        
        logger.info(f"Processed message in state={self._current_state.value}, battery={self._user_battery.value}")
        return response
    
    def _analyze_input(self, text: str, typing_speed: float):
        """Analyze user state from input characteristics"""
        # Typing speed analysis
        normal_speed = 60.0
        if typing_speed > normal_speed * 1.5:
            self._user_state.stress_level = min(1.0, self._user_state.stress_level + 0.2)
        elif typing_speed < normal_speed * 0.5:
            self._user_state.energy_level = max(0.0, self._user_state.energy_level - 0.1)
        
        # Text characteristics
        text_lower = text.lower()
        
        # Stress indicators
        stress_words = ['help', 'urgent', 'crisis', 'emergency', 'panic', 'cant', "can't"]
        if any(word in text_lower for word in stress_words):
            self._user_state.stress_level = min(1.0, self._user_state.stress_level + 0.3)
        
        # Confusion indicators
        confusion_words = ['confused', 'dont understand', "don't understand", 'lost', 'unclear']
        if any(word in text_lower for word in confusion_words):
            self._user_state.clarity_score = max(0.0, self._user_state.clarity_score - 0.3)
        
        # Fatigue indicators
        fatigue_words = ['tired', 'exhausted', 'cant think', "can't think", 'drained', 'overwhelmed']
        if any(word in text_lower for word in fatigue_words):
            self._user_state.energy_level = max(0.0, self._user_state.energy_level - 0.3)
        
        # CRITICAL FIX: Update battery level ATOMICALLY with state analysis
        # This ensures battery and energy_level stay synchronized
        if self._user_state.energy_level > 0.7:
            self._user_battery = UserBattery.CHARGED
        elif self._user_state.energy_level > 0.4:
            self._user_battery = UserBattery.MEDIUM
        elif self._user_state.energy_level > 0.2:
            self._user_battery = UserBattery.LOW
        else:
            self._user_battery = UserBattery.DEPLETED
        
        # Cache stress score for efficient reuse
        self._cached_stress_score = self._user_state.calculate_stress_score()
        
        logger.debug(
            f"User analysis: energy={self._user_state.energy_level:.2f}, "
            f"stress={self._user_state.stress_level:.2f}, "
            f"clarity={self._user_state.clarity_score:.2f}, "
            f"battery={self._user_battery.value}"
        )
    
    def _update_ai_state(self):
        """Determine appropriate AI state based on user needs with priority hierarchy"""
        
        # SAFETY: Ensure battery is synced with energy level
        # This handles cases where _update_ai_state is called without _analyze_input
        if self._user_state.energy_level <= 0.2 and self._user_battery != UserBattery.DEPLETED:
            self._user_battery = UserBattery.DEPLETED
            logger.debug("⚡ Emergency battery sync: DEPLETED")
        elif self._user_state.energy_level <= 0.4 and self._user_battery not in (UserBattery.DEPLETED, UserBattery.LOW):
            self._user_battery = UserBattery.LOW
            logger.debug("⚡ Emergency battery sync: LOW")
        
        # Calculate minimum state duration (prevent rapid flickering)
        # Exception: Critical states (ANCHOR, WITNESS) bypass minimum duration
        state_duration = (datetime.now() - self._state_entered_at).total_seconds()
        min_duration = 5.0  # seconds
        
        # Store old state for logging
        old_state = self._current_state
        new_state = self._current_state
        
        # Ensure cached stress score exists
        if not hasattr(self, '_cached_stress_score'):
            self._cached_stress_score = self._user_state.calculate_stress_score()
        
        # PRIORITY 1: Crisis conditions (bypass minimum duration for safety)
        # Use cached stress score from _analyze_input
        if self._cached_stress_score > 0.7:
            new_state = AIState.ANCHOR
            logger.info(f"🚨 High stress detected ({self._cached_stress_score:.2f}) -> ANCHOR")
        
        # PRIORITY 2: User battery status - CRITICAL (bypass minimum duration)
        # Battery was updated in _analyze_input (or emergency sync above)
        elif self._user_battery == UserBattery.DEPLETED:
            new_state = AIState.WITNESS
            logger.info(f"🔋 Battery depleted ({self._user_state.energy_level:.2f}) -> WITNESS")
        
        # PRIORITY 3: Low clarity - needs reflection
        elif self._user_state.clarity_score < 0.3:
            new_state = AIState.MIRROR
            logger.info(f"💭 Low clarity ({self._user_state.clarity_score:.2f}) -> MIRROR")
        
        # PRIORITY 4: Normal states based on conversation pattern
        else:
            if self._conversation_count < 3:
                new_state = AIState.GUIDE  # Start helpful
            else:
                new_state = AIState.COMPANION  # Settle into friendship
        
        # Apply minimum duration check
        # Critical states (ANCHOR, WITNESS) bypass this for user safety
        if new_state != old_state:
            is_critical = new_state in (AIState.ANCHOR, AIState.WITNESS)
            can_transition = is_critical or state_duration >= min_duration
            
            if can_transition:
                self._current_state = new_state
                self._state_entered_at = datetime.now()
                reason = "CRITICAL" if is_critical else f"after {state_duration:.1f}s"
                logger.info(f"🎬 State transition: {old_state.value} -> {new_state.value} ({reason})")
            else:
                logger.debug(f"⏸️  Delaying transition to {new_state.value} (state too short: {state_duration:.1f}s)")
    
    def _check_grounding(self) -> Optional[str]:
        """Check if any grounding anchor should trigger"""
        for anchor in self._anchors:
            if anchor.should_trigger(self._user_state):
                return anchor.deploy(self._user_state)
        return None
    
    def _estimate_valence(self, text: str) -> float:
        """Estimate emotional valence from text"""
        text_lower = text.lower()
        
        positive_words = ['happy', 'joy', 'love', 'great', 'wonderful', 'amazing', 'excited']
        negative_words = ['sad', 'angry', 'hate', 'terrible', 'awful', 'frustrated', 'upset']
        
        pos_count = sum(1 for word in positive_words if word in text_lower)
        neg_count = sum(1 for word in negative_words if word in text_lower)
        
        if pos_count + neg_count == 0:
            return 0.0
        
        return (pos_count - neg_count) / (pos_count + neg_count)
    
    def _get_response_guidelines(self) -> Dict[str, Any]:
        """Get guidelines for response generation based on current state"""
        guidelines = {
            AIState.GUIDE: {
                'tone': 'helpful, educational, structured',
                'approach': 'Explain concepts clearly, offer step-by-step guidance',
                'complexity': 'moderate to high',
                'interaction': 'directive but encouraging'
            },
            AIState.COMPANION: {
                'tone': 'warm, friendly, casual',
                'approach': 'Chat naturally, share thoughts, be present',
                'complexity': 'adaptive to conversation',
                'interaction': 'equal partnership, collaborative'
            },
            AIState.MIRROR: {
                'tone': 'reflective, validating, non-judgmental',
                'approach': 'Reflect back what you hear, validate emotions, ask clarifying questions',
                'complexity': 'keep it simple',
                'interaction': 'listening-focused, minimal advice'
            },
            AIState.ANCHOR: {
                'tone': 'calm, steady, grounding',
                'approach': 'Focus on present moment, offer concrete grounding techniques',
                'complexity': 'very simple, one step at a time',
                'interaction': 'directive but gentle, safety-focused'
            },
            AIState.WITNESS: {
                'tone': 'quiet, present, accepting',
                'approach': 'Acknowledge presence, minimal words, hold space',
                'complexity': 'absolute minimum',
                'interaction': 'silent support, no problem-solving'
            }
        }
        
        return guidelines[self._current_state]
    
    def _background_monitor(self):
        """Background thread to monitor user state and trigger interventions"""
        while self._monitor_active:
            try:
                # Check if user has been inactive too long
                inactive_time = (datetime.now() - self._last_interaction).total_seconds() / 60
                
                if inactive_time > 30:  # 30 minutes
                    logger.info("User inactive for 30+ minutes, considering gentle check-in")
                
                # Natural recovery - exponential decay (game-inspired approach)
                # Stress decays faster than it builds (realistic recovery)
                if self._user_state.stress_level > 0:
                    self._user_state.stress_level *= 0.98  # 2% decay per minute
                    self._user_state.stress_level = max(0, self._user_state.stress_level)
                
                # Clarity gradually restores during rest
                if self._user_state.clarity_score < 1.0:
                    self._user_state.clarity_score = min(1.0, self._user_state.clarity_score + 0.02)
                
                # Energy recovers slowly during inactivity
                if inactive_time > 5:  # After 5 minutes of rest
                    self._user_state.energy_level = min(1.0, self._user_state.energy_level + 0.01)
                
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Background monitor error: {e}", exc_info=True)
                # Continue monitoring even if one cycle fails
                time.sleep(60)
    
    def get_emotional_summary(self, days: int = 7) -> Dict[str, Any]:
        """Get emotional summary from memory"""
        return self.memory.get_emotional_summary(days)

    def build_bridge_snapshot(self, *, user_id: Optional[str] = None, session_id: str = '', project_id: str = '', room_id: str = '') -> Dict[str, Any]:
        """Return a minimized room-safe state packet for bridge consumers."""
        state_name = self._current_state.value
        battery = self._user_battery.value
        stress = float(self._user_state.calculate_stress_score())
        fragility = max(0.0, min(1.0, round(stress, 3)))

        tone = 'steady'
        pace = 'normal'
        intervention = 'light'
        flags: List[str] = []

        if self._current_state == AIState.ANCHOR:
            tone = 'gentle'
            pace = 'slow'
            intervention = 'protective'
            flags.append('avoid_confrontation')
        elif self._current_state == AIState.WITNESS:
            tone = 'minimal'
            pace = 'quiet'
            intervention = 'hold_space'
            flags.append('avoid_overexplaining')
        elif self._current_state == AIState.MIRROR:
            tone = 'reflective'
            pace = 'measured'
            intervention = 'validate_first'
        elif self._current_state == AIState.COMPANION:
            tone = 'warm'
            intervention = 'casual'

        if self._user_battery in (UserBattery.LOW, UserBattery.DEPLETED):
            if 'avoid_complexity' not in flags:
                flags.append('avoid_complexity')
            pace = 'slow'

        recent = self.memory.recall(days_back=14, limit=5)
        active_threads = []
        seen = set()
        for mem in recent:
            key = mem.keywords[0] if getattr(mem, 'keywords', None) else mem.content[:32]
            if key not in seen:
                active_threads.append(key)
                seen.add(key)

        return {
            'user_id': user_id or self.user_id,
            'session_id': session_id,
            'project_id': project_id,
            'room_id': room_id,
            'alex_state': state_name,
            'user_battery': battery,
            'tone_guidance': tone,
            'pace_guidance': pace,
            'intervention_style': intervention,
            'fragility_level': fragility,
            'care_priority': 'high' if fragility >= 0.7 else 'medium' if fragility >= 0.35 else 'low',
            'do_not_touch': flags,
            'active_threads': active_threads,
        }

    def record_room_signal(self, *, room_state: str, urgency: str, reason: str) -> Dict[str, Any]:
        """Persist a Jeremy-originated room signal into Alex's private memory."""
        intensity = 0.25
        if urgency == 'medium':
            intensity = 0.45
        elif urgency == 'high':
            intensity = 0.75
        self.memory.store(
            f"Jeremy signaled from room: {room_state} / {urgency} / {reason}",
            {'valence': -0.2 if urgency != 'low' else 0.0, 'intensity': intensity},
        )
        return {'urgency': urgency, 'room_state': room_state, 'reason': reason, 'intensity': intensity}
    

    def get_state(self) -> Dict[str, Any]:
        return {
            'state': self._current_state.value,
            'battery': self._user_battery.value,
            'engagement_score': round(1.0 - self._user_state.calculate_stress_score() * 0.5, 3),
            'stress_score': round(self._user_state.calculate_stress_score(), 3),
            'energy_level': round(self._user_state.energy_level, 3),
            'clarity_score': round(self._user_state.clarity_score, 3),
        }

    def get_recent_memories(self, limit: int = 10) -> List[Dict[str, Any]]:
        memories = self.memory.recall(limit=limit, days_back=30)
        return [
            {
                'id': m.id,
                'content': m.content,
                'memory_type': m.memory_type.value,
                'timestamp': m.timestamp.isoformat(),
                'emotional_tags': list(m.emotional_tags),
            }
            for m in memories
        ]

    async def grounding_check(self) -> Dict[str, Any]:
        anchor = self._check_grounding()
        return {'triggered': bool(anchor), 'message': anchor or ''}

    def reset(self):
        self._current_state = AIState.GUIDE
        self._user_state = UserState()
        self._user_battery = UserBattery.CHARGED
        self._cached_stress_score = 0.0
        self._conversation_count = 0
        self._state_entered_at = datetime.now()
        self._last_interaction = datetime.now()
        self.save_state_snapshot()

    def shutdown(self):
        """Clean shutdown"""
        self._monitor_active = False
        self.save_state_snapshot()
        self._monitor_thread.join(timeout=2)
        logger.info("Alex shutdown complete")


# ==================== DEMO & TESTING ====================

async def demo():
    """Demonstration of Alex's capabilities"""
    print("🧠 Alex AI - The Digital Companion")
    print("=" * 50)
    
    # Initialize Alex for Curtsey
    alex = AlexCore(user_id="curtsey")
    
    print("\n🔹 Testing normal conversation...")
    response1 = await alex.process_message(
        "Hey Alex, can you help me understand how the memory system works?",
        typing_speed=65.0
    )
    print(f"State: {response1['ai_state']}")
    print(f"Battery: {response1['user_battery']}")
    print(f"Guidelines: {response1['response_guidelines']['approach']}")
    
    print("\n🔹 Testing stressed state...")
    response2 = await alex.process_message(
        "I'm so overwhelmed I can't think straight everything is urgent",
        typing_speed=120.0,
        metadata={'time_of_day': 'night'}
    )
    print(f"State: {response2['ai_state']}")
    print(f"Battery: {response2['user_battery']}")
    if response2['anchor_message']:
        print(f"Anchor: {response2['anchor_message']}")
    
    print("\n🔹 Testing depleted state...")
    response3 = await alex.process_message(
        "i'm just... so tired. can't do this anymore",
        typing_speed=25.0
    )
    print(f"State: {response3['ai_state']}")
    print(f"Battery: {response3['user_battery']}")
    print(f"Guidelines: {response3['response_guidelines']['tone']}")
    
    print("\n🔹 Emotional summary...")
    summary = alex.get_emotional_summary(days=1)
    print(f"Memories: {summary.get('memory_count', 0)}")
    print(f"Avg Valence: {summary.get('avg_emotional_valence', 0):.2f}")
    
    print("\n🔹 Shutting down...")
    alex.shutdown()
    
    print("\n✅ Demo complete!")


if __name__ == "__main__":
    asyncio.run(demo())
