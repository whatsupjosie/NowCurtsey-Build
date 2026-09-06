"""
CONTEXT-AWARE EMOTION DISAMBIGUATION ENGINE
© 2024-2025 Rear View Foresight LLC

The REAL intelligence layer that understands:
- WHO is experiencing the emotion (actor vs subject)
- WHAT is the source/trigger
- WHY it matters (context & relationships)
- INTENSITY and TRAJECTORY
- WHAT ACTION fits this specific context

Solves the core problem: distinguishing "I took a shot" (achievement) 
from "I was shot" (trauma) from "I shot someone" (guilt/conflict).

This is the missing piece that makes the EQ layer actually WORK.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Set
from enum import Enum
from datetime import datetime

logger = logging.getLogger("disambiguation")


# ============================================================================
# ACTOR IDENTIFICATION
# ============================================================================

class ActorRole(Enum):
    """Who is experiencing the emotion?"""
    SELF = "self"  # User is directly experiencing it
    OTHER = "other"  # Someone else is experiencing it
    GROUP = "group"  # A group is experiencing it
    UNCLEAR = "unclear"  # Can't determine


class SubjectRole(Enum):
    """What/who is the target or subject?"""
    SELF = "self"  # The action/emotion is about them
    OTHER = "other"  # The action/emotion is about someone else
    GROUP = "group"  # The action/emotion is about a group
    ABSTRACT = "abstract"  # It's about an idea/situation/event
    UNCLEAR = "unclear"  # Can't determine


# ============================================================================
# CONTEXT CATEGORIES
# ============================================================================

class EmotionContext(Enum):
    """What domain/situation is this emotion happening in?"""
    
    # Achievement/Success contexts
    ACHIEVEMENT = "achievement"  # Success, accomplishment, winning
    MILESTONE = "milestone"  # Reaching a goal or target
    PERFORMANCE = "performance"  # Doing well at something
    CREATIVITY = "creativity"  # Making something new
    
    # Relationship contexts
    INTERPERSONAL = "interpersonal"  # Conflict with someone
    INTIMACY = "intimacy"  # Closeness/distance in relationships
    SOCIAL = "social"  # Belonging, acceptance, inclusion
    FAMILY = "family"  # Family-specific dynamics
    
    # Trauma/Crisis contexts
    VIOLENCE = "violence"  # Physical harm, assault, violence
    LOSS = "loss"  # Death, breakup, loss of something important
    BETRAYAL = "betrayal"  # Trust violation
    ABANDONMENT = "abandonment"  # Being left, rejected
    
    # Work/Identity contexts
    IDENTITY = "identity"  # Who they are, self-concept
    AUTONOMY = "autonomy"  # Freedom, control, agency
    COMPETENCE = "competence"  # Ability, capability
    PURPOSE = "purpose"  # Meaning, direction, goals
    
    # Health contexts
    HEALTH = "health"  # Physical/mental health
    FATIGUE = "fatigue"  # Tiredness, burnout
    PAIN = "pain"  # Physical or emotional pain
    
    # Mixed/Unclear
    UNCLEAR = "unclear"  # Can't determine context


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class DisambiguationResult:
    """Output of context-aware analysis"""
    
    # Actor analysis
    actor_role: ActorRole  # Who's experiencing it
    subject_role: SubjectRole  # What/who is it about
    
    # Context analysis
    primary_context: EmotionContext
    secondary_context: Optional[EmotionContext]
    
    # Intensity
    intensity: float  # 0.0-1.0 (neutral to crisis)
    valence: float  # -1.0 (negative) to +1.0 (positive)
    
    # Trajectory
    is_improving: Optional[bool]  # Direction of change
    
    # Confidence & reasoning
    confidence: float  # 0.0-1.0, how sure we are
    reasoning: List[str]  # Why we think this
    
    # Card selection guidance
    recommended_response_style: str  # "supportive", "celebratory", "practical", etc
    sensitive_areas: List[str]  # Topics to avoid
    opportunities: List[str]  # What might help


@dataclass  
class ConversationContext:
    """Tracks multi-turn conversation for disambiguation"""
    user_id: str
    message_history: List[Dict] = field(default_factory=list)
    inferred_relationships: Dict[str, str] = field(default_factory=dict)  # person_name -> relationship
    recent_topics: Set[str] = field(default_factory=set)
    emotional_trend: List[float] = field(default_factory=list)  # Recent intensity values
    
    def add_message(self, speaker: str, text: str, emotion_intensity: float):
        """Add a message to conversation history"""
        self.message_history.append({
            "speaker": speaker,
            "text": text,
            "timestamp": datetime.now().isoformat(),
            "emotion_intensity": emotion_intensity,
        })
        self.emotional_trend.append(emotion_intensity)
        # Keep last 20 messages and intensities
        if len(self.message_history) > 20:
            self.message_history.pop(0)
            self.emotional_trend.pop(0)


# ============================================================================
# PATTERN LIBRARIES (The Context Dictionary)
# ============================================================================

class ContextPatterns:
    """Hardcoded patterns for recognizing context"""
    
    def __init__(self):
        # ACTION VERBS: "I shot", "they shot", "someone shot me"
        self.action_verbs = {
            "shot": {
                "achievement": ["I shot the winning goal", "I shot a perfect score", "I shot it", "got a shot off"],
                "violence": ["I was shot", "they shot me", "he shot me", "shot at me", "got shot"],
                "self_harm": ["I shot myself"],
                "guilt": ["I shot him", "I shot them", "I shot someone"],
            },
            "hurt": {
                "physical": ["I hurt my leg", "I hurt my back", "physically hurt"],
                "emotional": ["I hurt her", "I hurt them", "I hurt someone"],
                "self": ["I hurt myself", "I hurt me"],
            },
            "broken": {
                "physical": ["I broke my arm", "I broke my leg", "I broke something"],
                "emotional": ["I broke down", "broken up about", "my heart is broken"],
                "relationship": ["we broke up", "we're broken up"],
                "system": ["broke the system", "broke the code"],
            },
            "lost": {
                "achievement": ["I lost the game", "we lost", "they lost"],
                "disappearance": ["I lost my keys", "I lost my phone"],
                "death": ["I lost my mother", "I lost my friend", "lost someone"],
                "emotional": ["I lost it", "lost my mind", "lost myself"],
            },
            "hit": {
                "success": ["I hit the target", "I hit my goal", "hit it out of the park"],
                "violence": ["I hit him", "I hit someone", "he hit me", "I was hit"],
                "accident": ["I hit the car", "I hit the wall"],
            },
        }
        
        # EMOTIONAL STATE MARKERS
        self.emotional_markers = {
            "pride": ["proud", "proud of", "achievement", "accomplished", "made it"],
            "grief": ["lost someone", "mourning", "funeral", "death", "passed away"],
            "guilt": ["my fault", "I'm sorry", "shouldn't have", "regret", "I messed up"],
            "fear": ["scared", "afraid", "terrified", "anxious", "worried"],
            "anger": ["angry", "mad", "furious", "rage", "infuriated"],
            "shame": ["ashamed", "embarrassed", "humiliated", "mortified"],
            "hopelessness": ["can't do", "impossible", "never", "give up", "worthless"],
        }
        
        # RELATIONSHIP INDICATORS
        self.relationship_words = {
            "family": ["mom", "dad", "mother", "father", "sister", "brother", "son", "daughter", "parent", "sibling"],
            "romantic": ["boyfriend", "girlfriend", "husband", "wife", "partner", "spouse", "lover"],
            "friend": ["friend", "best friend", "buddy", "mate", "pal", "companion"],
            "professional": ["boss", "manager", "coworker", "colleague", "employer", "employee"],
            "authority": ["cop", "police", "officer", "authority", "teacher", "coach"],
        }
        
        # TEMPORAL MARKERS (recency)
        self.recency_markers = {
            "immediate": ["just", "right now", "now", "this second", "today"],
            "recent": ["yesterday", "last night", "few days ago", "week ago"],
            "historical": ["years ago", "long time ago", "before", "used to"],
            "ongoing": ["still", "continuing", "keeps happening", "repeated"],
        }


# ============================================================================
# CORE DISAMBIGUATION ENGINE
# ============================================================================

class ContextDisambiguator:
    """
    Analyzes a message in conversation context to understand:
    - WHO is experiencing emotion (actor)
    - WHAT/WHO it's about (subject)
    - WHAT DOMAIN it's in (context)
    - HOW INTENSE (intensity)
    - WHICH DIRECTION (trajectory)
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("disambiguator")
        self.patterns = ContextPatterns()
        self.conversation_contexts: Dict[str, ConversationContext] = {}
    
    def analyze(
        self,
        message: str,
        user_id: str,
        speaker: str = "user",
        include_history: bool = True,
    ) -> DisambiguationResult:
        """
        Analyze a message to understand its emotional and contextual meaning.
        
        Args:
            message: The user's text
            user_id: User identifier for conversation tracking
            speaker: Who's speaking (usually "user")
            include_history: Whether to consider conversation history
        
        Returns:
            DisambiguationResult with detailed analysis
        """
        
        # Get or create conversation context
        if user_id not in self.conversation_contexts:
            self.conversation_contexts[user_id] = ConversationContext(user_id=user_id)
        
        conv_ctx = self.conversation_contexts[user_id]
        
        # Step 1: Analyze text directly
        actor = self._identify_actor(message)
        subject = self._identify_subject(message)
        context = self._identify_context(message)
        intensity = self._estimate_intensity(message)
        valence = self._estimate_valence(message)
        trajectory = self._estimate_trajectory(message, conv_ctx)
        
        # Step 2: Refine with conversation history
        if include_history and len(conv_ctx.message_history) > 1:
            actor, subject, context = self._refine_with_history(
                message, actor, subject, context, conv_ctx
            )
        
        # Step 3: Generate reasoning
        reasoning = self._build_reasoning(
            message, actor, subject, context, intensity, valence
        )
        
        # Step 4: Determine response guidance
        response_style = self._recommend_response_style(actor, subject, context, intensity)
        sensitive_areas = self._identify_sensitive_areas(actor, subject, context, conv_ctx)
        opportunities = self._identify_opportunities(actor, subject, context, intensity, valence)
        
        # Step 5: Update conversation context
        conv_ctx.add_message(speaker, message, intensity)
        self._extract_relationships(message, conv_ctx)
        self._extract_topics(message, conv_ctx)
        
        # Confidence is lower if actor or subject unclear
        confidence = 0.8
        if actor == ActorRole.UNCLEAR:
            confidence -= 0.2
        if subject == SubjectRole.UNCLEAR:
            confidence -= 0.15
        
        confidence = max(0.3, min(1.0, confidence))
        
        return DisambiguationResult(
            actor_role=actor,
            subject_role=subject,
            primary_context=context[0],
            secondary_context=context[1] if len(context) > 1 else None,
            intensity=intensity,
            valence=valence,
            is_improving=trajectory,
            confidence=confidence,
            reasoning=reasoning,
            recommended_response_style=response_style,
            sensitive_areas=sensitive_areas,
            opportunities=opportunities,
        )
    
    # ========================================================================
    # ACTOR IDENTIFICATION ("Who is experiencing this?")
    # ========================================================================
    
    def _identify_actor(self, message: str) -> ActorRole:
        """
        Determine who is experiencing the emotion.
        "I" vs "He/She/They" vs "We" vs "People in general"
        """
        msg_lower = message.lower()
        
        # First person (self)
        if re.search(r'\b(i|me|my|mine|myself)\b', msg_lower):
            return ActorRole.SELF
        
        # Third person (other)
        if re.search(r'\b(he|she|they|him|her|them|his|her|their)\b', msg_lower):
            return ActorRole.OTHER
        
        # First person plural (group/us)
        if re.search(r'\b(we|us|our|ours|ourselves|my team)\b', msg_lower):
            return ActorRole.GROUP
        
        return ActorRole.UNCLEAR
    
    # ========================================================================
    # SUBJECT IDENTIFICATION ("What/who is it about?")
    # ========================================================================
    
    def _identify_subject(self, message: str) -> SubjectRole:
        """
        Determine what or who the action/emotion is directed at.
        Is it about THEM, about SOMEONE ELSE, or about a SITUATION?
        """
        msg_lower = message.lower()
        
        # The action happens TO the actor (self-directed)
        self_directed = re.search(
            r'(hurt myself|shot myself|broke myself|blame myself|hurt me|took it out on myself)',
            msg_lower
        )
        if self_directed:
            return SubjectRole.SELF
        
        # The action happens to someone else
        other_directed = re.search(
            r'(hurt (?:them|him|her|you|someone)| shot (?:them|him|her|you)|yelled at|blamed)',
            msg_lower
        )
        if other_directed:
            return SubjectRole.OTHER
        
        # The action is about a group
        group_directed = re.search(
            r'(hurt my family|team|group|them all|the company|the department)',
            msg_lower
        )
        if group_directed:
            return SubjectRole.GROUP
        
        # Abstract/situational (about a concept, event, situation)
        abstract = re.search(
            r'(the situation|everything|it|the system|my life|my future|the world)',
            msg_lower
        )
        if abstract:
            return SubjectRole.ABSTRACT
        
        return SubjectRole.UNCLEAR
    
    # ========================================================================
    # CONTEXT IDENTIFICATION ("What domain is this in?")
    # ========================================================================
    
    def _identify_context(self, message: str) -> List[EmotionContext]:
        """
        Identify what domain/category this emotion belongs to.
        Returns primary + optional secondary context.
        """
        msg_lower = message.lower()
        contexts = []
        
        # Check achievement contexts
        if re.search(r'\b(won|won the|scored|goal|success|achieved|accomplished|made it)\b', msg_lower):
            contexts.append(EmotionContext.ACHIEVEMENT)
        
        # Check violence/harm contexts
        if re.search(
            r'\b(shot|hit|beaten|attacked|assault|violence|rape|abuse|harm)\b',
            msg_lower
        ):
            # Distinguish between "I shot a goal" vs "I was shot"
            if not re.search(r'\b(shot (?:a goal|the winning|it|the target))\b', msg_lower):
                contexts.append(EmotionContext.VIOLENCE)
        
        # Check loss/grief contexts
        if re.search(
            r'\b(lost someone|lost my|death|died|passed away|funeral|mourning)\b',
            msg_lower
        ):
            contexts.append(EmotionContext.LOSS)
        
        # Check betrayal/relationship contexts
        if re.search(
            r'\b(betrayed|lied|cheated|broke my trust|broke up|affair|infidelity)\b',
            msg_lower
        ):
            if re.search(r'\b(my (?:friend|partner|family|boyfriend|girlfriend))\b', msg_lower):
                contexts.append(EmotionContext.BETRAYAL)
            else:
                contexts.append(EmotionContext.INTERPERSONAL)
        
        # Check identity/self-concept contexts
        if re.search(
            r'\b(who i am|my identity|what i am|belong|my values|my beliefs|who\'s speaking)\b',
            msg_lower
        ):
            contexts.append(EmotionContext.IDENTITY)
        
        # Check autonomy/control contexts
        if re.search(
            r'\b(can\'t|cannot|forced|stuck|trapped|no control|no choice)\b',
            msg_lower
        ):
            contexts.append(EmotionContext.AUTONOMY)
        
        # Check fatigue/burnout contexts
        if re.search(
            r'\b(tired|exhausted|burned out|drained|overwhelmed|running on empty|no energy)\b',
            msg_lower
        ):
            contexts.append(EmotionContext.FATIGUE)
        
        # Default if nothing matched
        if not contexts:
            contexts.append(EmotionContext.UNCLEAR)
        
        return contexts
    
    # ========================================================================
    # INTENSITY ESTIMATION
    # ========================================================================
    
    def _estimate_intensity(self, message: str) -> float:
        """
        Estimate emotional intensity on 0.0-1.0 scale.
        0.0 = neutral, 1.0 = crisis level
        """
        msg_lower = message.lower()
        
        # Crisis markers (0.9-1.0)
        if re.search(
            r'\b(suicide|kill myself|end it|give up|hopeless|dying|can\'t go on)\b',
            msg_lower
        ):
            return 1.0
        
        # High intensity (0.7-0.9)
        if re.search(
            r'\b(devastated|horrified|terrified|rage|can\'t breathe)\b',
            msg_lower
        ):
            return 0.85
        
        # Moderate-high (0.5-0.7)
        if re.search(
            r'\b(upset|angry|sad|scared|anxious|hurting)\b',
            msg_lower
        ):
            return 0.65
        
        # Moderate (0.3-0.5)
        if re.search(
            r'\b(frustrated|concerned|worried|bothered|bothers me)\b',
            msg_lower
        ):
            return 0.45
        
        # Low (0.1-0.3)
        if re.search(
            r'\b(fine|okay|alright|good|nice|happy|proud)\b',
            msg_lower
        ):
            return 0.25
        
        # Neutral/baseline
        return 0.5
    
    # ========================================================================
    # VALENCE ESTIMATION (negative vs positive)
    # ========================================================================
    
    def _estimate_valence(self, message: str) -> float:
        """
        Estimate emotional valence: -1.0 (negative) to +1.0 (positive)
        """
        msg_lower = message.lower()
        
        positive_words = [
            "good", "happy", "great", "awesome", "love", "proud", "won",
            "achieved", "success", "accomplished", "excited", "thrilled"
        ]
        
        negative_words = [
            "bad", "sad", "terrible", "awful", "hate", "angry", "lost",
            "failed", "devastated", "hurt", "upset", "scared"
        ]
        
        pos_count = sum(1 for word in positive_words if re.search(rf"\b{re.escape(word)}\b", msg_lower))
        neg_count = sum(1 for word in negative_words if re.search(rf"\b{re.escape(word)}\b", msg_lower))
        
        if pos_count + neg_count == 0:
            return 0.0
        
        return (pos_count - neg_count) / (pos_count + neg_count)
    
    # ========================================================================
    # TRAJECTORY ESTIMATION (is this getting better/worse?)
    # ========================================================================
    
    def _estimate_trajectory(self, message: str, ctx: ConversationContext) -> Optional[bool]:
        """
        Estimate if emotional state is improving or worsening.
        True = improving, False = worsening, None = unclear
        """
        if len(ctx.emotional_trend) < 2:
            return None
        
        recent_intensity = ctx.emotional_trend[-1]
        previous_intensity = ctx.emotional_trend[-2]
        
        # If intensity is decreasing, probably improving
        if recent_intensity < previous_intensity * 0.8:
            return True
        
        # If intensity is increasing, probably worsening
        if recent_intensity > previous_intensity * 1.2:
            return False
        
        return None
    
    # ========================================================================
    # REFINEMENT WITH HISTORY
    # ========================================================================
    
    def _refine_with_history(
        self,
        message: str,
        actor: ActorRole,
        subject: SubjectRole,
        context: List[EmotionContext],
        conv_ctx: ConversationContext,
    ) -> Tuple[ActorRole, SubjectRole, List[EmotionContext]]:
        """
        Use conversation history to refine initial analysis.
        Example: "I shot it" is ambiguous, but if they previously mentioned
        basketball, it's likely achievement, not violence.
        """
        # If context is VIOLENCE but recent topics include sports/games,
        # might actually be ACHIEVEMENT
        if EmotionContext.VIOLENCE in context:
            for topic in conv_ctx.recent_topics:
                if topic in ["basketball", "football", "soccer", "sports", "game", "competition"]:
                    context = [EmotionContext.ACHIEVEMENT]
                    break
        
        return actor, subject, context
    
    # ========================================================================
    # REASONING GENERATION
    # ========================================================================
    
    def _build_reasoning(
        self,
        message: str,
        actor: ActorRole,
        subject: SubjectRole,
        context: List[EmotionContext],
        intensity: float,
        valence: float,
    ) -> List[str]:
        """Generate human-readable reasoning for the analysis"""
        reasons = []
        
        if actor == ActorRole.SELF:
            reasons.append("User is directly experiencing this")
        elif actor == ActorRole.OTHER:
            reasons.append("User is describing someone else's experience")
        elif actor == ActorRole.GROUP:
            reasons.append("User is describing a group experience")
        
        if subject == SubjectRole.SELF:
            reasons.append("This is about the user themselves")
        elif subject == SubjectRole.OTHER:
            reasons.append("This is about impact on someone else")
        
        if context:
            reasons.append(f"Primary context: {context[0].value}")
        
        if intensity > 0.8:
            reasons.append("High emotional intensity detected")
        elif intensity < 0.3:
            reasons.append("Low emotional intensity")
        
        if valence > 0.5:
            reasons.append("Predominantly positive valence")
        elif valence < -0.5:
            reasons.append("Predominantly negative valence")
        
        return reasons
    
    # ========================================================================
    # RESPONSE GUIDANCE
    # ========================================================================
    
    def _recommend_response_style(
        self,
        actor: ActorRole,
        subject: SubjectRole,
        context: List[EmotionContext],
        intensity: float,
    ) -> str:
        """What type of response would be most appropriate?"""
        
        # High intensity always needs support
        if intensity > 0.8:
            if EmotionContext.VIOLENCE in context or EmotionContext.LOSS in context:
                return "crisis_support"
            return "emotional_support"
        
        # Achievement/success
        if context and context[0] == EmotionContext.ACHIEVEMENT:
            return "celebratory"
        
        # Conflict/relationship issues
        if context and context[0] in [EmotionContext.INTERPERSONAL, EmotionContext.BETRAYAL]:
            return "conflict_resolution"
        
        # Fatigue/burnout
        if context and context[0] == EmotionContext.FATIGUE:
            return "practical_support"
        
        # Default
        return "general_support"
    
    def _identify_sensitive_areas(
        self,
        actor: ActorRole,
        subject: SubjectRole,
        context: List[EmotionContext],
        conv_ctx: ConversationContext,
    ) -> List[str]:
        """What topics should we be careful about?"""
        sensitive = []
        
        if context and EmotionContext.LOSS in context:
            sensitive.append("don't minimize their grief")
            sensitive.append("avoid cheerful platitudes")
        
        if context and EmotionContext.BETRAYAL in context:
            sensitive.append("don't defend the other person")
            sensitive.append("don't dismiss their feelings")
        
        if context and EmotionContext.VIOLENCE in context:
            sensitive.append("this is potentially trauma-related")
            sensitive.append("avoid victim-blaming language")
        
        return sensitive
    
    def _identify_opportunities(
        self,
        actor: ActorRole,
        subject: SubjectRole,
        context: List[EmotionContext],
        intensity: float,
        valence: float,
    ) -> List[str]:
        """What might actually help?"""
        opportunities = []
        
        if context and context[0] == EmotionContext.ACHIEVEMENT:
            opportunities.append("celebrate this with them")
            opportunities.append("ask what's next")
        
        if intensity > 0.7 and valence < 0:
            opportunities.append("validate their feelings")
            opportunities.append("offer specific support")
            opportunities.append("check if they need crisis resources")
        
        if context and context[0] == EmotionContext.FATIGUE:
            opportunities.append("normalize burnout")
            opportunities.append("suggest recovery practices")
        
        return opportunities
    
    # ========================================================================
    # CONTEXT EXTRACTION
    # ========================================================================
    
    def _extract_relationships(self, message: str, ctx: ConversationContext):
        """Extract who people are talking about"""
        msg_lower = message.lower()
        
        for rel_type, keywords in self.patterns.relationship_words.items():
            for keyword in keywords:
                if keyword in msg_lower:
                    # Try to extract the person's name (very simple)
                    pattern = rf'{keyword}\s+(\w+)'
                    match = re.search(pattern, msg_lower)
                    if match:
                        name = match.group(1)
                        ctx.inferred_relationships[name] = rel_type
    
    def _extract_topics(self, message: str, ctx: ConversationContext):
        """Extract what they're talking about"""
        msg_lower = message.lower()
        
        topics = [
            "basketball", "football", "soccer", "sports", "game",
            "work", "job", "boss", "company", "career",
            "relationship", "breakup", "dating", "marriage",
            "health", "illness", "sick", "pain",
            "school", "college", "university", "learning",
            "family", "parent", "sibling", "child",
        ]
        
        for topic in topics:
            if topic in msg_lower:
                ctx.recent_topics.add(topic)


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    disambiguator = ContextDisambiguator()
    
    # Test cases
    test_messages = [
        ("I shot the winning goal!", "user1"),
        ("I was shot in the shoulder", "user1"),
        ("I lost the game", "user2"),
        ("I lost my mother last month", "user2"),
        ("I hurt myself", "user3"),
        ("I hurt him and I feel terrible", "user3"),
        ("We broke up", "user4"),
        ("I broke my leg", "user4"),
    ]
    
    for message, user_id in test_messages:
        result = disambiguator.analyze(message, user_id)
        print(f"\nMessage: {message}")
        print(f"Actor: {result.actor_role.value}")
        print(f"Subject: {result.subject_role.value}")
        print(f"Context: {result.primary_context.value}")
        print(f"Intensity: {result.intensity:.2f}")
        print(f"Valence: {result.valence:.2f}")
        print(f"Response Style: {result.recommended_response_style}")
        print(f"Confidence: {result.confidence:.2f}")
        print(f"Reasoning: {result.reasoning}")
