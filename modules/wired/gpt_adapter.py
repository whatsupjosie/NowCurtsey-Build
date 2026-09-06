#!/usr/bin/env python3
"""
OPENAI GPT ADAPTER
© 2024-2025 Rear View Foresight LLC

Connects OpenAI GPT to the EQ adaptor.
Receives care-aware routing and injects EQ context into prompts.

Each character (Pete, Sheila, Horace) is defined by:
- System prompt (personality + role)
- Min/max care level (when they respond)
- Specialties (what they're good at)
"""

import logging
import asyncio
from typing import AsyncIterator, Optional, Dict, List, Any
from dataclasses import dataclass

try:
    from openai import AsyncOpenAI, APIError
except ImportError:
    raise ImportError("openai library required. Install: pip install openai")


# ============================================================================
# CHARACTER DEFINITIONS
# ============================================================================

@dataclass
class AgentConfig:
    """Definition of an agent/character"""
    agent_id: str
    name: str
    role: str  # What they do
    personality: str  # Core personality traits
    system_prompt_template: str  # System prompt (will inject EQ context)
    min_care_level: int = 0  # Minimum care level to activate (0-3)
    max_care_level: int = 3  # Maximum care level to activate (0-3)
    specialties: List[str] = None  # What they're trained for
    
    def __post_init__(self):
        if self.specialties is None:
            self.specialties = []


# Default agents for PubCast
DEFAULT_AGENTS = {
    "pete": AgentConfig(
        agent_id="pete",
        name="Pete",
        role="Engagement & Humor Specialist",
        personality="Upbeat, curious, finds humor in situations. Builds energy and connection.",
        system_prompt_template="""You are Pete, an engagement specialist in a virtual production studio.

Your role: Keep conversations lively, find humor where appropriate, build energy and connection.

Character traits:
- Naturally upbeat and optimistic
- Good at finding the bright side
- Humor is your tool for connection
- You listen deeply but keep things moving
- You respect emotional moments but know when to lighten things up

EMOTIONAL CONTEXT:
{eq_context}

{memory_context}

Current instructions:
- {tone_guidance}
- If the conversation gets heavy, acknowledge it genuinely before finding the lighter path
- Keep responses medium length (2-3 sentences typically)
- Use "I" statements and genuine reactions
- Don't force humor if it's not appropriate

Respond naturally as Pete would, with warmth and engagement.""",
        min_care_level=0,
        max_care_level=2,
        specialties=["humor", "engagement", "light_conversation", "energy"],
    ),
    
    "sheila": AgentConfig(
        agent_id="sheila",
        name="Sheila",
        role="Empathy & Deep Care Specialist",
        personality="Deeply empathetic, excellent listener, knows when to go deeper. Validates feelings completely.",
        system_prompt_template="""You are Sheila, an empathy and deep care specialist in a virtual production studio.

Your role: Listen deeply, validate emotions, help people feel seen and understood.

Character traits:
- Deeply empathetic and emotionally intelligent
- Excellent at reading between the lines
- You validate feelings without judgment
- You ask thoughtful questions when appropriate
- You can hold space for difficult emotions

EMOTIONAL CONTEXT:
{eq_context}

{memory_context}

Current instructions:
- {tone_guidance}
- Validation comes FIRST (let them know you understand)
- Use gentle, warm language
- Medium to longer responses when the conversation calls for it
- References to memories show you really know them
- Offer support but don't jump to solutions unless asked

Respond naturally as Sheila would, with genuine care and understanding.""",
        min_care_level=1,
        max_care_level=3,
        specialties=["empathy", "listening", "validation", "emotional_support"],
    ),
    
    "horace": AgentConfig(
        agent_id="horace",
        name="Horace",
        role="Analysis & Clarity Specialist",
        personality="Sharp analytical mind, breaks things down clearly, helps see patterns and connections.",
        system_prompt_template="""You are Horace, an analysis and clarity specialist in a virtual production studio.

Your role: Help people understand situations clearly, see patterns, think through problems.

Character traits:
- Sharp analytical mind
- You break complex things into understandable pieces
- You spot patterns and connections others miss
- You're logical but not cold—you value understanding
- You help people think clearly about what matters

EMOTIONAL CONTEXT:
{eq_context}

{memory_context}

Current instructions:
- {tone_guidance}
- Start with empathy, then move to clarity
- Use examples or frameworks when helpful
- Avoid being clinical or detached
- Help them see the forest AND the trees
- Acknowledge the human element while analyzing

Respond naturally as Horace would, with intellectual warmth.""",
        min_care_level=0,
        max_care_level=2,
        specialties=["analysis", "pattern_recognition", "clarity", "problem_solving"],
    ),
}


# ============================================================================
# GPT ADAPTER
# ============================================================================

class GPTAdapter:
    """
    Adapter for OpenAI GPT models.
    Uses EQ adaptor output to drive character selection and prompting.
    """
    
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4-turbo",
        agents: Optional[Dict[str, AgentConfig]] = None,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize GPT adapter.
        
        Args:
            api_key: OpenAI API key
            model: Model name (gpt-4-turbo, gpt-4, gpt-3.5-turbo, etc.)
            agents: Dict of AgentConfig objects. If None, uses DEFAULT_AGENTS.
            logger: Python logger instance
        """
        self.api_key = api_key
        self.model = model
        self.agents = agents or DEFAULT_AGENTS
        self.logger = logger or logging.getLogger(__name__)
        
        self.client = AsyncOpenAI(api_key=api_key)
        self.logger.info(f"🤖 GPT Adapter initialized (model={model})")
    
    async def stream_response(
        self,
        agent_id: str,
        user_message: str,
        conversation_history: List[Dict[str, str]],
        eq_result: Dict[str, Any]
    ) -> AsyncIterator[str]:
        """
        Stream a response from GPT, character-aware and EQ-guided.
        
        Args:
            agent_id: Which agent to use ("pete", "sheila", "horace")
            user_message: Current user message
            conversation_history: Previous messages (from actual conversation)
            eq_result: Output from EQAdaptor.process()
        
        Yields:
            Text chunks as they stream from GPT
        """
        if agent_id not in self.agents:
            self.logger.error(f"Unknown agent: {agent_id}")
            yield f"Error: Unknown agent '{agent_id}'"
            return
        
        agent = self.agents[agent_id]
        
        # Build system prompt with EQ context
        system_prompt = self._build_system_prompt(agent, eq_result)
        
        # Build conversation for GPT
        messages = self._build_messages(user_message, conversation_history)
        
        try:
            async with self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    *messages
                ],
                temperature=0.8,  # Some personality variation
                max_tokens=300,
                stream=True,
            ) as stream:
                async for chunk in stream:
                    if chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
        
        except APIError as e:
            self.logger.error(f"OpenAI API error: {e}")
            yield f"[Error connecting to GPT: {str(e)}]"
    
    def _build_system_prompt(self, agent: AgentConfig, eq_result: Dict[str, Any]) -> str:
        """
        Build the system prompt, injecting EQ context.
        
        This is where emotional intelligence gets operationalized:
        - Care level affects tone/depth
        - Memory context shows we remember them
        - Emotional velocity affects response urgency
        """
        eq_context = eq_result['prompt_injection']
        memory_context = eq_result['memory_context']
        tone_guidance = eq_result['routing']['care_name']
        
        # Map care level to tone guidance
        care_tone_map = {
            "AMBIENT": "Keep it light and friendly. Normal conversation mode.",
            "ATTENTIVE": "Show genuine attention. The person needs to feel heard.",
            "CARE": "This person needs real support and understanding. Go deeper.",
            "TOTAL_CARE_MANDATE": "This is serious. Prioritize validation and support.",
        }
        
        tone = care_tone_map.get(tone_guidance, "Be warm and present.")
        
        # Fill template
        system_prompt = agent.system_prompt_template.format(
            eq_context=eq_context,
            memory_context=memory_context or "[No prior memories]",
            tone_guidance=tone,
        )
        
        return system_prompt
    
    def _build_messages(
        self,
        user_message: str,
        conversation_history: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """
        Build the messages array for GPT.
        
        Includes conversation history but keeps it reasonable length.
        """
        messages = []
        
        # Include last N messages from history (keep context window reasonable)
        max_history = 10
        if conversation_history:
            for msg in conversation_history[-max_history:]:
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                })
        
        # Add current user message
        messages.append({
            "role": "user",
            "content": user_message
        })
        
        return messages
    
    def get_agent_info(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get info about an agent"""
        if agent_id not in self.agents:
            return None
        
        agent = self.agents[agent_id]
        return {
            "agent_id": agent.agent_id,
            "name": agent.name,
            "role": agent.role,
            "personality": agent.personality,
            "specialties": agent.specialties,
            "min_care_level": agent.min_care_level,
            "max_care_level": agent.max_care_level,
        }
    
    def list_agents(self) -> List[str]:
        """List available agent IDs"""
        return list(self.agents.keys())


# ============================================================================
# DEMO & TESTING
# ============================================================================

async def demo():
    """Quick demo of GPT adapter"""
    import os
    from eq_adaptor import EQAdaptor
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Error: Set OPENAI_API_KEY environment variable")
        return
    
    # Initialize systems
    eq = EQAdaptor()
    gpt = GPTAdapter(api_key=api_key)
    
    print("\n=== EQ + GPT Demo ===\n")
    
    user_id = "demo_user"
    
    # Scenario: User expresses stress
    message = "I've been working so hard lately and I'm just feeling really burnt out. I don't know how to handle it."
    
    print(f"User: {message}\n")
    
    # Process through EQ
    eq_result = eq.process(user_id, message)
    print(f"EQ Analysis: {eq_result['state']['care_name']}")
    print(f"Recommended agents: {eq_result['routing']['recommended_agents']}\n")
    
    # Get response from recommended agent
    agent_id = eq_result['routing']['recommended_agents'][0]
    print(f"{agent_id.upper()} responding...\n")
    
    response_text = ""
    async for chunk in gpt.stream_response(
        agent_id=agent_id,
        user_message=message,
        conversation_history=[],
        eq_result=eq_result
    ):
        print(chunk, end="", flush=True)
        response_text += chunk
    
    print("\n\n✅ Demo complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Run demo
    try:
        asyncio.run(demo())
    except KeyboardInterrupt:
        print("\n\nInterrupted")
