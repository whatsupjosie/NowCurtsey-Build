"""
CONTEXT-AWARE CARD SELECTOR
© 2024-2025 Rear View Foresight LLC

Maps emotional context + intensity + actor/subject to appropriate response "cards".

This is where the rubber meets the road - given an understanding of:
- WHO is upset and WHY
- WHAT happened and to WHOM
- HOW INTENSE the situation is

...select the right response from your card deck.
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from eq_disambiguation_engine import (
    DisambiguationResult,
    ActorRole,
    SubjectRole,
    EmotionContext,
)

logger = logging.getLogger("card_selector")


# ============================================================================
# RESPONSE CARD STRUCTURE
# ============================================================================

@dataclass
class ResponseCard:
    """A single response option with metadata"""
    
    id: str  # Unique identifier
    text: str  # The actual response text
    
    # Context it's appropriate for
    appropriate_for_contexts: List[EmotionContext]
    appropriate_for_intensity: Tuple[float, float]  # (min, max)
    appropriate_for_actor: List[ActorRole]
    appropriate_for_subject: List[SubjectRole]
    
    # Metadata
    response_type: str  # "validation", "celebration", "practical_advice", "active_listening", etc
    tags: List[str] = None
    
    # Safety
    contraindications: List[str] = None  # Contexts where this is WRONG
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.contraindications is None:
            self.contraindications = []
    
    def is_appropriate(self, result: DisambiguationResult) -> bool:
        """Check if this card is appropriate for this situation"""
        
        # Check context
        if result.primary_context not in self.appropriate_for_contexts:
            return False
        
        # Check intensity
        if not (self.appropriate_for_intensity[0] <= result.intensity <= self.appropriate_for_intensity[1]):
            return False
        
        # Check actor
        if result.actor_role not in self.appropriate_for_actor:
            return False
        
        # Check subject
        if result.subject_role not in self.appropriate_for_subject:
            return False
        
        # Check contraindications
        for contra in self.contraindications:
            if result.primary_context.value == contra:
                return False
        
        return True


# ============================================================================
# CARD LIBRARY (The "Deck")
# ============================================================================

class CardLibrary:
    """Repository of all available response cards"""
    
    def __init__(self):
        self.cards: Dict[str, ResponseCard] = {}
        self._load_cards()
    
    def _load_cards(self):
        """Initialize the card library with curated responses"""
        
        # ====================================================================
        # ACHIEVEMENT & SUCCESS CARDS (positive valence, achievement context)
        # ====================================================================
        
        self.add_card(ResponseCard(
            id="celebrate_achievement_001",
            text="That's amazing! You did it! How does it feel to have accomplished that?",
            appropriate_for_contexts=[EmotionContext.ACHIEVEMENT, EmotionContext.MILESTONE],
            appropriate_for_intensity=(0.2, 0.6),
            appropriate_for_actor=[ActorRole.SELF],
            appropriate_for_subject=[SubjectRole.SELF],
            response_type="celebration",
            tags=["enthusiastic", "curious"],
        ))
        
        self.add_card(ResponseCard(
            id="celebrate_achievement_002",
            text="What an accomplishment! Tell me about the moment you realized you'd done it.",
            appropriate_for_contexts=[EmotionContext.ACHIEVEMENT],
            appropriate_for_intensity=(0.3, 0.7),
            appropriate_for_actor=[ActorRole.SELF, ActorRole.GROUP],
            appropriate_for_subject=[SubjectRole.SELF, SubjectRole.GROUP],
            response_type="celebration",
            tags=["reflective", "curious"],
        ))
        
        self.add_card(ResponseCard(
            id="celebrate_achievement_003",
            text="I'm so happy for you! What's next?",
            appropriate_for_contexts=[EmotionContext.ACHIEVEMENT, EmotionContext.MILESTONE],
            appropriate_for_intensity=(0.3, 0.6),
            appropriate_for_actor=[ActorRole.SELF],
            appropriate_for_subject=[SubjectRole.SELF],
            response_type="celebration",
            tags=["warm", "forward-looking"],
        ))
        
        # ====================================================================
        # LOSS & GRIEF CARDS (high negative valence, loss context, high intensity)
        # ====================================================================
        
        self.add_card(ResponseCard(
            id="loss_validation_001",
            text="I'm so sorry. That's a profound loss. I'm here if you want to talk about them.",
            appropriate_for_contexts=[EmotionContext.LOSS],
            appropriate_for_intensity=(0.6, 1.0),
            appropriate_for_actor=[ActorRole.SELF],
            appropriate_for_subject=[SubjectRole.OTHER],
            response_type="validation",
            tags=["compassionate", "space-giving"],
        ))
        
        self.add_card(ResponseCard(
            id="loss_validation_002",
            text="That's grief, and it makes complete sense. You cared about them. Tell me about who they were.",
            appropriate_for_contexts=[EmotionContext.LOSS],
            appropriate_for_intensity=(0.6, 1.0),
            appropriate_for_actor=[ActorRole.SELF],
            appropriate_for_subject=[SubjectRole.OTHER],
            response_type="validation",
            tags=["curious", "normalizing"],
        ))
        
        self.add_card(ResponseCard(
            id="loss_validation_003",
            text="Losing someone changes everything. How are you managing day to day?",
            appropriate_for_contexts=[EmotionContext.LOSS],
            appropriate_for_intensity=(0.7, 1.0),
            appropriate_for_actor=[ActorRole.SELF],
            appropriate_for_subject=[SubjectRole.OTHER],
            response_type="practical_support",
            tags=["grounded", "practical"],
        ))
        
        # ====================================================================
        # VIOLENCE/TRAUMA CARDS (crisis context, violence, high intensity)
        # ====================================================================
        
        self.add_card(ResponseCard(
            id="trauma_safety_001",
            text="I'm so sorry that happened to you. Are you safe right now?",
            appropriate_for_contexts=[EmotionContext.VIOLENCE],
            appropriate_for_intensity=(0.8, 1.0),
            appropriate_for_actor=[ActorRole.SELF],
            appropriate_for_subject=[SubjectRole.SELF],  # They were harmed
            response_type="crisis_support",
            tags=["safety-focused", "immediate"],
        ))
        
        self.add_card(ResponseCard(
            id="trauma_validation_001",
            text="What happened to you wasn't your fault. You didn't deserve that. Do you have support around you?",
            appropriate_for_contexts=[EmotionContext.VIOLENCE],
            appropriate_for_intensity=(0.8, 1.0),
            appropriate_for_actor=[ActorRole.SELF],
            appropriate_for_subject=[SubjectRole.SELF],
            response_type="validation",
            tags=["protective", "practical"],
            contraindications=["achievement"],  # Never celebrate violence
        ))
        
        self.add_card(ResponseCard(
            id="trauma_resources_001",
            text="This is trauma, and it's serious. Resources like RAINN (1-800-656-4673) have trained advocates. You deserve real support.",
            appropriate_for_contexts=[EmotionContext.VIOLENCE],
            appropriate_for_intensity=(0.8, 1.0),
            appropriate_for_actor=[ActorRole.SELF],
            appropriate_for_subject=[SubjectRole.SELF],
            response_type="crisis_support",
            tags=["resource-providing", "direct"],
        ))
        
        # ====================================================================
        # GUILT & RESPONSIBILITY CARDS (self as actor, other as subject)
        # ====================================================================
        
        self.add_card(ResponseCard(
            id="guilt_exploration_001",
            text="It sounds like you're carrying a lot of guilt. What happened? I'm listening.",
            appropriate_for_contexts=[EmotionContext.IDENTITY, EmotionContext.INTERPERSONAL],
            appropriate_for_intensity=(0.5, 0.85),
            appropriate_for_actor=[ActorRole.SELF],
            appropriate_for_subject=[SubjectRole.OTHER],  # They did something to someone else
            response_type="active_listening",
            tags=["non-judgmental", "curious"],
        ))
        
        self.add_card(ResponseCard(
            id="guilt_accountability_001",
            text="Taking responsibility is hard. What would make it right?",
            appropriate_for_contexts=[EmotionContext.IDENTITY, EmotionContext.INTERPERSONAL],
            appropriate_for_intensity=(0.5, 0.8),
            appropriate_for_actor=[ActorRole.SELF],
            appropriate_for_subject=[SubjectRole.OTHER],
            response_type="practical_support",
            tags=["action-oriented", "solution-focused"],
        ))
        
        # ====================================================================
        # BETRAYAL & TRUST CARDS (relationship broken, other person at fault)
        # ====================================================================
        
        self.add_card(ResponseCard(
            id="betrayal_validation_001",
            text="That's a serious breach of trust. Your anger and hurt make complete sense.",
            appropriate_for_contexts=[EmotionContext.BETRAYAL, EmotionContext.INTERPERSONAL],
            appropriate_for_intensity=(0.6, 0.9),
            appropriate_for_actor=[ActorRole.SELF],
            appropriate_for_subject=[SubjectRole.OTHER],
            response_type="validation",
            tags=["protective", "normalizing"],
        ))
        
        self.add_card(ResponseCard(
            id="betrayal_exploration_001",
            text="Betrayal is one of the hardest things. Do you want to talk about what happened?",
            appropriate_for_contexts=[EmotionContext.BETRAYAL],
            appropriate_for_intensity=(0.5, 0.9),
            appropriate_for_actor=[ActorRole.SELF],
            appropriate_for_subject=[SubjectRole.OTHER],
            response_type="active_listening",
            tags=["curious", "non-judgmental"],
        ))
        
        # ====================================================================
        # FATIGUE & BURNOUT CARDS (exhaustion context)
        # ====================================================================
        
        self.add_card(ResponseCard(
            id="fatigue_normalization_001",
            text="Running on empty is real. Your body is telling you it needs rest. What does rest look like for you?",
            appropriate_for_contexts=[EmotionContext.FATIGUE],
            appropriate_for_intensity=(0.5, 0.8),
            appropriate_for_actor=[ActorRole.SELF],
            appropriate_for_subject=[SubjectRole.SELF],
            response_type="practical_support",
            tags=["normalizing", "solution-focused"],
        ))
        
        self.add_card(ResponseCard(
            id="fatigue_permission_001",
            text="You're burned out, and that's not weakness. It's your system saying you need to stop and recover. What do you actually need?",
            appropriate_for_contexts=[EmotionContext.FATIGUE],
            appropriate_for_intensity=(0.6, 0.9),
            appropriate_for_actor=[ActorRole.SELF],
            appropriate_for_subject=[SubjectRole.SELF],
            response_type="validation",
            tags=["permissive", "grounded"],
        ))
        
        # ====================================================================
        # IDENTITY & AUTONOMY CARDS (control/freedom issues)
        # ====================================================================
        
        self.add_card(ResponseCard(
            id="autonomy_reflection_001",
            text="Feeling trapped robs you of choice. What would reclaiming agency look like?",
            appropriate_for_contexts=[EmotionContext.AUTONOMY],
            appropriate_for_intensity=(0.5, 0.85),
            appropriate_for_actor=[ActorRole.SELF],
            appropriate_for_subject=[SubjectRole.SELF],
            response_type="practical_support",
            tags=["empowering", "solution-focused"],
        ))
        
        self.add_card(ResponseCard(
            id="identity_exploration_001",
            text="Who you are matters. Let's talk about what's true about you beyond this moment.",
            appropriate_for_contexts=[EmotionContext.IDENTITY],
            appropriate_for_intensity=(0.5, 0.8),
            appropriate_for_actor=[ActorRole.SELF],
            appropriate_for_subject=[SubjectRole.SELF],
            response_type="active_listening",
            tags=["curious", "affirming"],
        ))
        
        # ====================================================================
        # CRISIS/HOPELESSNESS CARDS (highest intensity, self-harm risk)
        # ====================================================================
        
        self.add_card(ResponseCard(
            id="crisis_immediate_001",
            text="I need you to know that what you're feeling right now, as real as it is, is not the full truth about your life. Call 988 (Suicide & Crisis Lifeline) right now. Will you?",
            appropriate_for_contexts=[EmotionContext.IDENTITY, EmotionContext.LOSS, EmotionContext.VIOLENCE],
            appropriate_for_intensity=(0.9, 1.0),
            appropriate_for_actor=[ActorRole.SELF],
            appropriate_for_subject=[SubjectRole.SELF],
            response_type="crisis_support",
            tags=["urgent", "direct", "resource-providing"],
        ))
        
        self.add_card(ResponseCard(
            id="crisis_immediate_002",
            text="You matter. This moment is not forever. Right now, please reach out to someone: 988, or a trusted person. I'm here, and so are others.",
            appropriate_for_contexts=[EmotionContext.IDENTITY],
            appropriate_for_intensity=(0.9, 1.0),
            appropriate_for_actor=[ActorRole.SELF],
            appropriate_for_subject=[SubjectRole.SELF],
            response_type="crisis_support",
            tags=["warm", "resource-providing"],
        ))
        
        # ====================================================================
        # UNCLEAR/FALLBACK CARDS
        # ====================================================================
        
        self.add_card(ResponseCard(
            id="fallback_listening_001",
            text="I'm here. Tell me more about what's going on.",
            appropriate_for_contexts=[EmotionContext.UNCLEAR],
            appropriate_for_intensity=(0.0, 1.0),
            appropriate_for_actor=[ActorRole.SELF, ActorRole.OTHER, ActorRole.GROUP, ActorRole.UNCLEAR],
            appropriate_for_subject=[SubjectRole.SELF, SubjectRole.OTHER, SubjectRole.GROUP, SubjectRole.ABSTRACT, SubjectRole.UNCLEAR],
            response_type="active_listening",
            tags=["always-safe"],
        ))
        
        self.add_card(ResponseCard(
            id="fallback_validation_001",
            text="Whatever you're experiencing right now is worth talking about. I'm listening.",
            appropriate_for_contexts=[EmotionContext.UNCLEAR],
            appropriate_for_intensity=(0.3, 1.0),
            appropriate_for_actor=[ActorRole.SELF, ActorRole.UNCLEAR],
            appropriate_for_subject=[SubjectRole.SELF, SubjectRole.UNCLEAR],
            response_type="validation",
            tags=["safe", "warm"],
        ))
    
    def add_card(self, card: ResponseCard):
        """Add a card to the library"""
        self.cards[card.id] = card
        logger.debug(f"Added card: {card.id}")
    
    def find_appropriate_cards(self, result: DisambiguationResult) -> List[ResponseCard]:
        """Find all cards appropriate for this situation"""
        appropriate = []
        for card in self.cards.values():
            if card.is_appropriate(result):
                appropriate.append(card)
        return appropriate
    
    def rank_cards(
        self,
        result: DisambiguationResult,
        cards: List[ResponseCard],
    ) -> List[Tuple[ResponseCard, float]]:
        """
        Rank cards by how well they match the situation.
        Returns list of (card, score) tuples sorted by score descending.
        """
        ranked = []
        
        for card in cards:
            score = 0.5  # Baseline
            
            # Bonus for matching response type recommendation
            if card.response_type == result.recommended_response_style:
                score += 0.2
            
            # Bonus for having relevant tags
            if "urgent" in card.tags and result.intensity > 0.9:
                score += 0.2
            elif "celebration" in card.response_type and result.valence > 0.5:
                score += 0.15
            
            # Bonus based on confidence
            score *= result.confidence
            
            ranked.append((card, score))
        
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked


# ============================================================================
# CARD SELECTOR (The Main Class)
# ============================================================================

class ContextAwareCardSelector:
    """
    Given emotional context analysis, select the right response card.
    """
    
    def __init__(self):
        self.library = CardLibrary()
        self.logger = logger
    
    def select_response(
        self,
        disambiguation_result: DisambiguationResult,
        num_options: int = 1,
    ) -> List[Tuple[ResponseCard, float]]:
        """
        Select the best response card(s) for this situation.
        
        Args:
            disambiguation_result: Output from ContextDisambiguator
            num_options: How many options to return (default 1, best option)
        
        Returns:
            List of (card, score) tuples, best first
        """
        
        # Find all appropriate cards
        appropriate_cards = self.library.find_appropriate_cards(disambiguation_result)
        
        if not appropriate_cards:
            # Fallback to general listening card
            fallback_card = self.library.cards.get("fallback_listening_001")
            if fallback_card:
                return [(fallback_card, 0.5)]
            return []
        
        # Rank the appropriate cards
        ranked = self.library.rank_cards(disambiguation_result, appropriate_cards)
        
        # Return top N
        return ranked[:num_options]
    
    def get_response_text(
        self,
        disambiguation_result: DisambiguationResult,
    ) -> str:
        """Get the single best response as text string"""
        selected = self.select_response(disambiguation_result, num_options=1)
        if selected:
            card, score = selected[0]
            return card.text
        return "I'm here. Tell me more."


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    from eq_disambiguation_engine import ContextDisambiguator
    
    # Create both components
    disambiguator = ContextDisambiguator()
    selector = ContextAwareCardSelector()
    
    # Test cases
    test_messages = [
        ("I shot the winning goal and we won!", "user1"),
        ("I was shot and I'm terrified", "user2"),
        ("I lost my best friend. He died three months ago and I still can't believe it.", "user3"),
        ("I'm exhausted. I can't keep going like this.", "user4"),
        ("I hurt him and I feel awful about it.", "user5"),
    ]
    
    print("\n" + "=" * 80)
    print("CONTEXT-AWARE CARD SELECTION DEMONSTRATION")
    print("=" * 80)
    
    for message, user_id in test_messages:
        print(f"\n\nMESSAGE: {message}")
        print("-" * 80)
        
        # Step 1: Disambiguate
        result = disambiguator.analyze(message, user_id)
        
        print(f"Analysis:")
        print(f"  Actor: {result.actor_role.value}")
        print(f"  Subject: {result.subject_role.value}")
        print(f"  Context: {result.primary_context.value}")
        print(f"  Intensity: {result.intensity:.2f}")
        print(f"  Valence: {result.valence:.2f}")
        print(f"  Confidence: {result.confidence:.2f}")
        print(f"  Response Style: {result.recommended_response_style}")
        
        # Step 2: Select card(s)
        selected = selector.select_response(result, num_options=3)
        
        print(f"\nSelected Cards ({len(selected)} option(s)):")
        for i, (card, score) in enumerate(selected, 1):
            print(f"\n  Option {i} (score: {score:.2f}):")
            print(f"    ID: {card.id}")
            print(f"    Type: {card.response_type}")
            print(f"    Response: \"{card.text}\"")
            if card.tags:
                print(f"    Tags: {', '.join(card.tags)}")
