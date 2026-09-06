"""
EQ INTEGRATION LAYER
© 2024-2025 Rear View Foresight LLC

Connects the context disambiguation engine and card selector to your 
existing orchestrator, conversation engine, and EQ adaptor.

This is the "glue" that makes everything work together.
"""

import logging
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass

from eq_disambiguation_engine import ContextDisambiguator, DisambiguationResult
from eq_card_selector import ContextAwareCardSelector, ResponseCard

logger = logging.getLogger("eq_integration")


# ============================================================================
# INTEGRATED EQ RESPONSE (What orchestrator receives)
# ============================================================================

@dataclass
class EQIntegratedResponse:
    """
    Response that combines:
    - What we understood about the situation
    - What card we selected
    - How to actually respond
    """
    
    # Understanding
    disambiguation: DisambiguationResult
    
    # Selected response
    selected_card: ResponseCard
    selection_confidence: float
    
    # Alternative options (for UI/learning)
    alternative_cards: List[Tuple[ResponseCard, float]]
    
    # How to respond
    response_text: str
    response_type: str  # "validation", "celebration", "crisis_support", etc
    
    # Follow-up guidance
    follow_up_questions: List[str]
    resources_if_needed: List[str]
    
    # Metadata for logging/learning
    message_id: str
    user_id: str


# ============================================================================
# EQ ORCHESTRATOR (The Main Integration Point)
# ============================================================================

class EQOrchestrator:
    """
    Orchestrates the entire EQ understanding pipeline:
    1. Takes raw user message
    2. Disambiguates emotional context
    3. Selects appropriate response card
    4. Generates follow-up guidance
    5. Returns integrated response for system to use
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("eq_orchestrator")
        
        # Initialize components
        self.disambiguator = ContextDisambiguator(logger=self.logger)
        self.selector = ContextAwareCardSelector()
        
        # Tracking
        self.conversation_history: Dict[str, List[EQIntegratedResponse]] = {}
    
    def process_message(
        self,
        user_message: str,
        user_id: str,
        message_id: str = None,
        speaker: str = "user",
    ) -> EQIntegratedResponse:
        """
        Process a user message through the full EQ pipeline.
        
        Args:
            user_message: The raw text from user
            user_id: User identifier
            message_id: Optional message ID for tracking
            speaker: Who's speaking (usually "user")
        
        Returns:
            EQIntegratedResponse with understanding + selected response
        """
        
        if message_id is None:
            import uuid
            message_id = str(uuid.uuid4())[:8]
        
        # Step 1: Disambiguate
        self.logger.info(f"[{user_id}] Analyzing message: {user_message[:50]}...")
        disambiguation = self.disambiguator.analyze(
            message=user_message,
            user_id=user_id,
            speaker=speaker,
            include_history=True,
        )
        
        self.logger.debug(f"[{user_id}] Disambiguation result:")
        self.logger.debug(f"  Actor: {disambiguation.actor_role.value}")
        self.logger.debug(f"  Context: {disambiguation.primary_context.value}")
        self.logger.debug(f"  Intensity: {disambiguation.intensity:.2f}")
        self.logger.debug(f"  Confidence: {disambiguation.confidence:.2f}")
        
        # Step 2: Select card
        self.logger.info(f"[{user_id}] Selecting response card...")
        selected_cards = self.selector.select_response(disambiguation, num_options=3)
        
        if not selected_cards:
            self.logger.warning(f"[{user_id}] No cards selected, using fallback")
            selected_card = self.selector.library.cards.get("fallback_listening_001")
            selection_confidence = 0.3
            alternatives = []
        else:
            selected_card, selection_confidence = selected_cards[0]
            alternatives = selected_cards[1:]
            
            self.logger.debug(f"[{user_id}] Selected card: {selected_card.id}")
            self.logger.debug(f"  Response type: {selected_card.response_type}")
            self.logger.debug(f"  Confidence: {selection_confidence:.2f}")
        
        # Step 3: Generate follow-up questions based on context
        follow_ups = self._generate_follow_ups(disambiguation)
        
        # Step 4: Identify resources if needed
        resources = self._identify_resources(disambiguation)
        
        # Step 5: Create integrated response
        response = EQIntegratedResponse(
            disambiguation=disambiguation,
            selected_card=selected_card,
            selection_confidence=selection_confidence,
            alternative_cards=alternatives,
            response_text=selected_card.text,
            response_type=selected_card.response_type,
            follow_up_questions=follow_ups,
            resources_if_needed=resources,
            message_id=message_id,
            user_id=user_id,
        )
        
        # Step 6: Store in history for learning
        if user_id not in self.conversation_history:
            self.conversation_history[user_id] = []
        self.conversation_history[user_id].append(response)
        
        self.logger.info(f"[{user_id}] Response ready: {selected_card.response_type}")
        
        return response
    
    def _generate_follow_ups(self, result: DisambiguationResult) -> List[str]:
        """Generate thoughtful follow-up questions based on context"""
        follow_ups = []
        
        # Generic follow-up
        follow_ups.append("How are you feeling right now?")
        
        # Context-specific follow-ups
        if result.primary_context.value == "loss":
            follow_ups.append("Would you like to tell me about them?")
            follow_ups.append("How are you managing day to day?")
        
        elif result.primary_context.value == "achievement":
            follow_ups.append("What's next for you?")
            follow_ups.append("How does this change your path forward?")
        
        elif result.primary_context.value == "violence":
            follow_ups.append("Are you safe right now?")
            follow_ups.append("Do you have someone you trust to talk to?")
        
        elif result.primary_context.value == "betrayal":
            follow_ups.append("How did they respond when confronted?")
            follow_ups.append("What would help you move forward?")
        
        elif result.primary_context.value == "fatigue":
            follow_ups.append("What does rest look like for you?")
            follow_ups.append("What would help you recover?")
        
        elif result.primary_context.value == "identity":
            follow_ups.append("What's true about you beyond this moment?")
            follow_ups.append("What do you need to remember about yourself?")
        
        elif result.primary_context.value == "autonomy":
            follow_ups.append("What would reclaiming agency look like?")
            follow_ups.append("What's one thing you can control here?")
        
        # If high intensity, add safety check
        if result.intensity > 0.8:
            follow_ups.insert(0, "Do you have immediate support around you?")
        
        return follow_ups[:3]  # Return top 3
    
    def _identify_resources(self, result: DisambiguationResult) -> List[str]:
        """Identify crisis/support resources if needed"""
        resources = []
        
        # Crisis support
        if result.intensity > 0.9 or result.primary_context.value == "violence":
            resources.append("Crisis Text Line: Text HOME to 741741")
            resources.append("National Suicide Prevention Lifeline: 988")
            resources.append("RAINN (sexual assault): 1-800-656-4673")
        
        # Grief support
        if result.primary_context.value == "loss":
            resources.append("GriefShare online support groups")
            resources.append("The Dinner Party (for young adults experiencing loss)")
        
        # Trauma support
        if result.primary_context.value == "violence":
            resources.append("ISSTD (trauma specialists directory)")
            resources.append("EMDR International Association for trauma therapists")
        
        # General mental health
        if result.intensity > 0.6:
            resources.append("Psychology Today therapist finder")
            resources.append("SAMHSA National Helpline: 1-800-662-4357")
        
        return resources
    
    def get_user_trajectory(self, user_id: str) -> Dict:
        """Analyze user's emotional trajectory over conversation"""
        if user_id not in self.conversation_history:
            return {"intensity_trend": [], "valence_trend": []}
        
        history = self.conversation_history[user_id]
        intensities = [r.disambiguation.intensity for r in history]
        valences = [r.disambiguation.valence for r in history]
        
        # Calculate trend
        is_improving = None
        if len(intensities) > 1:
            recent_avg = sum(intensities[-3:]) / min(3, len(intensities))
            earlier_avg = sum(intensities[:3]) / min(3, len(intensities))
            if recent_avg < earlier_avg * 0.8:
                is_improving = True
            elif recent_avg > earlier_avg * 1.2:
                is_improving = False
        
        return {
            "intensity_trend": intensities,
            "valence_trend": valences,
            "is_improving": is_improving,
            "num_messages": len(history),
            "average_intensity": sum(intensities) / len(intensities) if intensities else 0.5,
        }


# ============================================================================
# ORCHESTRATOR BRIDGE (Connects to main.py orchestrator)
# ============================================================================

class EQOrchestratorBridge:
    """
    Bridges EQ orchestrator to existing WiredOrchestrator in main.py
    
    Usage in main.py:
        eq_bridge = EQOrchestratorBridge(orchestrator)
        
        # In websocket handler:
        eq_response = await eq_bridge.process_user_message(
            message=user_input,
            user_id=user_id,
            room_id=room_id,
        )
        
        # Now you have both EQ understanding + response selection:
        print(eq_response.response_text)
        print(eq_response.follow_up_questions)
        print(eq_response.resources_if_needed)
    """
    
    def __init__(self, existing_orchestrator=None, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("eq_bridge")
        self.existing_orchestrator = existing_orchestrator
        self.eq_orchestrator = EQOrchestrator(logger=self.logger)
    
    async def process_user_message(
        self,
        message: str,
        user_id: str,
        room_id: str = "default",
        message_id: str = None,
    ) -> EQIntegratedResponse:
        """
        Process message through EQ pipeline.
        Can optionally also call existing orchestrator for other agents.
        """
        
        self.logger.info(f"[{user_id}:{room_id}] Processing message through EQ pipeline")
        
        # Process through EQ system
        eq_response = self.eq_orchestrator.process_message(
            user_message=message,
            user_id=user_id,
            message_id=message_id,
        )
        
        # Optionally: Call existing orchestrator for other agents
        if self.existing_orchestrator:
            try:
                self.logger.debug(f"[{user_id}] Also calling existing orchestrator...")
                existing_response = await self.existing_orchestrator.handle_message(
                    room_id=room_id,
                    user_id=user_id,
                    text=message,
                )
                # Could combine responses here if needed
            except Exception as e:
                self.logger.error(f"Existing orchestrator error: {e}")
        
        return eq_response
    
    def get_user_analysis(self, user_id: str) -> Dict:
        """Get complete analysis of user's emotional state and trajectory"""
        trajectory = self.eq_orchestrator.get_user_trajectory(user_id)
        
        if user_id in self.eq_orchestrator.conversation_history:
            last_response = self.eq_orchestrator.conversation_history[user_id][-1]
            current_state = {
                "actor": last_response.disambiguation.actor_role.value,
                "context": last_response.disambiguation.primary_context.value,
                "intensity": last_response.disambiguation.intensity,
                "valence": last_response.disambiguation.valence,
                "confidence": last_response.disambiguation.confidence,
            }
        else:
            current_state = None
        
        return {
            "current_state": current_state,
            "trajectory": trajectory,
        }


# ============================================================================
# HELPER: Integration with Conversation Engine
# ============================================================================

class EQConversationBridge:
    """
    Optionally bridges EQ with your existing ConversationEngine
    for hybrid approach: EQ understanding + intent-based responses
    """
    
    def __init__(self, conversation_engine, eq_orchestrator: EQOrchestrator):
        self.conv_engine = conversation_engine
        self.eq_orchestrator = eq_orchestrator
        self.logger = logging.getLogger("eq_conv_bridge")
    
    def get_best_response(
        self,
        message: str,
        user_id: str,
        use_eq: bool = True,
        use_intent: bool = True,
    ) -> Dict:
        """
        Get response using either/both EQ and intent matching.
        
        use_eq=True:    Use context-aware EQ selection
        use_intent=True: Use conversation engine intent matching
        
        If both, EQ + Intent can reinforce each other.
        """
        
        result = {
            "message": message,
            "user_id": user_id,
            "using_eq": False,
            "using_intent": False,
            "eq_response": None,
            "intent_response": None,
            "recommended_response": None,
        }
        
        # Get EQ response
        if use_eq:
            self.logger.info(f"[{user_id}] Getting EQ response...")
            eq_response = self.eq_orchestrator.process_message(message, user_id)
            result["eq_response"] = {
                "text": eq_response.response_text,
                "type": eq_response.response_type,
                "context": eq_response.disambiguation.primary_context.value,
                "intensity": eq_response.disambiguation.intensity,
                "confidence": eq_response.selection_confidence,
            }
            result["using_eq"] = True
        
        # Get intent response
        if use_intent:
            self.logger.info(f"[{user_id}] Getting intent response...")
            intent_response = self.conv_engine.generate(message, user_id=user_id)
            result["intent_response"] = {
                "text": intent_response,
                "method": "intent_matching",
            }
            result["using_intent"] = True
        
        # Decide which to use
        if use_eq and use_intent:
            # If EQ confidence is high, trust EQ
            if result["eq_response"]["confidence"] > 0.7:
                result["recommended_response"] = result["eq_response"]["text"]
                result["method"] = "eq_high_confidence"
            # If intensity is high, trust EQ (safety first)
            elif result["eq_response"]["intensity"] > 0.6:
                result["recommended_response"] = result["eq_response"]["text"]
                result["method"] = "eq_high_intensity"
            # Otherwise use intent
            else:
                result["recommended_response"] = result["intent_response"]["text"]
                result["method"] = "intent_matching"
        elif use_eq:
            result["recommended_response"] = result["eq_response"]["text"]
            result["method"] = "eq_only"
        else:
            result["recommended_response"] = result["intent_response"]["text"]
            result["method"] = "intent_only"
        
        return result


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(name)s - %(levelname)s - %(message)s'
    )
    
    # Create EQ orchestrator
    eq_orchestrator = EQOrchestrator()
    
    # Test messages
    test_cases = [
        ("I shot the winning goal and my team is celebrating!", "user1"),
        ("I was shot in a robbery and I'm terrified", "user2"),
        ("I lost my dad six months ago and some days I can't get out of bed", "user3"),
        ("I'm so exhausted I can barely function anymore", "user4"),
        ("I hurt my best friend and I feel horrible about it", "user5"),
        ("Nothing matters anymore. I don't see the point in continuing", "user6"),
    ]
    
    print("\n" + "=" * 100)
    print("EQ ORCHESTRATOR INTEGRATION DEMONSTRATION")
    print("=" * 100)
    
    for message, user_id in test_cases:
        print(f"\n\n{'='*100}")
        print(f"USER MESSAGE: {message}")
        print(f"{'='*100}")
        
        # Process through EQ
        eq_response = eq_orchestrator.process_message(message, user_id)
        
        # Display understanding
        print(f"\n📊 UNDERSTANDING:")
        print(f"  Actor: {eq_response.disambiguation.actor_role.value}")
        print(f"  Subject: {eq_response.disambiguation.subject_role.value}")
        print(f"  Context: {eq_response.disambiguation.primary_context.value}")
        print(f"  Intensity: {eq_response.disambiguation.intensity:.2f}/1.0")
        print(f"  Valence: {eq_response.disambiguation.valence:.2f} (negative to positive)")
        print(f"  Confidence: {eq_response.disambiguation.confidence:.0%}")
        
        # Display selected response
        print(f"\n💬 SELECTED RESPONSE:")
        print(f"  Type: {eq_response.response_type}")
        print(f"  Confidence: {eq_response.selection_confidence:.0%}")
        print(f"  Card ID: {eq_response.selected_card.id}")
        print(f"  Response: \"{eq_response.response_text}\"")
        
        # Display alternative options
        if eq_response.alternative_cards:
            print(f"\n🔄 ALTERNATIVE OPTIONS:")
            for alt_card, alt_score in eq_response.alternative_cards:
                print(f"  • [{alt_score:.0%}] {alt_card.id}")
                print(f"    \"{alt_card.text}\"")
        
        # Display follow-ups
        if eq_response.follow_up_questions:
            print(f"\n❓ FOLLOW-UP QUESTIONS:")
            for q in eq_response.follow_up_questions:
                print(f"  • {q}")
        
        # Display resources
        if eq_response.resources_if_needed:
            print(f"\n📞 RESOURCES (if needed):")
            for resource in eq_response.resources_if_needed:
                print(f"  • {resource}")
        
        # Display user trajectory
        trajectory = eq_orchestrator.get_user_trajectory(user_id)
        if trajectory["num_messages"] > 1:
            print(f"\n📈 EMOTIONAL TRAJECTORY:")
            print(f"  Messages in conversation: {trajectory['num_messages']}")
            print(f"  Average intensity: {trajectory['average_intensity']:.2f}")
            print(f"  Trend: {trajectory['is_improving']}")
