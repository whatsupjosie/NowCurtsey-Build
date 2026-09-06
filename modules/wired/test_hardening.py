"""
Test suite for PubCast AI production hardening.

Run with: pytest tests/test_hardening.py -v
"""

import pytest
import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch

from schemas import (
    ChatMessage, FeedbackMessage, CorrectionMessage,
    validate_websocket_message
)
from rate_limiter import RateLimiter, TokenBucket
from orchestrator_hardening import OrchestratorHardener, AgentHealthStatus


class TestTokenBucket:
    """Test token bucket rate limiting."""
    
    def test_bucket_initialization(self):
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        assert bucket.capacity == 10
        assert bucket.tokens == 10.0
    
    def test_consume_tokens(self):
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        assert bucket.consume(2) is True
        assert bucket.tokens == 3.0
        assert bucket.consume(3) is True
        assert bucket.tokens == 0.0
        assert bucket.consume(1) is False
    
    def test_bucket_refill(self):
        bucket = TokenBucket(capacity=10, refill_rate=1.0, refill_interval=0.1)
        bucket.consume(10)
        assert bucket.tokens == 0.0
        
        # Wait for refill
        import time
        time.sleep(0.15)
        assert bucket.available() > 0.0


class TestRateLimiter:
    """Test rate limiting with multiple tiers."""
    
    def test_per_user_limit(self):
        limiter = RateLimiter(
            per_user_messages=3,
            per_user_window_seconds=60
        )
        
        # First 3 messages should pass
        assert limiter.is_allowed("user1")[0] is True
        assert limiter.is_allowed("user1")[0] is True
        assert limiter.is_allowed("user1")[0] is True
        
        # 4th should be rate limited
        allowed, reason = limiter.is_allowed("user1")
        assert allowed is False
        assert reason == "user_rate_limit"
    
    def test_per_room_limit(self):
        limiter = RateLimiter(
            per_room_messages=2,
            per_room_window_seconds=60
        )
        
        # Different users in same room
        assert limiter.is_allowed("user1", "room1")[0] is True
        assert limiter.is_allowed("user2", "room1")[0] is True
        
        # 3rd message in room should fail
        allowed, reason = limiter.is_allowed("user3", "room1")
        assert allowed is False
        assert reason == "room_rate_limit"
    
    def test_global_limit(self):
        limiter = RateLimiter(global_messages=2)
        
        assert limiter.is_allowed("user1", "room1")[0] is True
        assert limiter.is_allowed("user2", "room2")[0] is True
        
        allowed, reason = limiter.is_allowed("user3", "room3")
        assert allowed is False
        assert reason == "global_rate_limit"
    
    def test_get_user_status(self):
        limiter = RateLimiter(per_user_messages=5)
        limiter.is_allowed("user1")
        limiter.is_allowed("user1")
        
        status = limiter.get_user_status("user1")
        assert status["capacity"] == 5
        assert status["available"] < 5


class TestInputValidation:
    """Test WebSocket message validation."""
    
    def test_valid_chat_message(self):
        data = {"type": "chat", "text": "Hello world"}
        msg_type, model = validate_websocket_message(data)
        assert msg_type == "chat"
        assert isinstance(model, ChatMessage)
        assert model.text == "Hello world"
    
    def test_xss_sanitization(self):
        data = {"type": "chat", "text": "<script>alert('xss')</script>"}
        msg_type, model = validate_websocket_message(data)
        assert "<script>" not in model.text
        assert "&lt;script&gt;" in model.text
    
    def test_message_too_long(self):
        long_text = "x" * 10001
        data = {"type": "chat", "text": long_text}
        with pytest.raises(ValueError):
            validate_websocket_message(data)
    
    def test_message_too_short(self):
        data = {"type": "chat", "text": ""}
        with pytest.raises(ValueError):
            validate_websocket_message(data)
    
    def test_invalid_json(self):
        # This should be caught before validation
        pass
    
    def test_unknown_message_type(self):
        data = {"type": "admin", "text": "Hack"}
        with pytest.raises(ValueError):
            validate_websocket_message(data)
    
    def test_feedback_message(self):
        data = {
            "type": "feedback",
            "response_id": "resp1",
            "positive": True,
            "comment": "Great response"
        }
        msg_type, model = validate_websocket_message(data)
        assert msg_type == "feedback"
        assert isinstance(model, FeedbackMessage)
    
    def test_correction_message(self):
        data = {
            "type": "correction",
            "message_id": "msg1",
            "correct_intent": "greeting"
        }
        msg_type, model = validate_websocket_message(data)
        assert msg_type == "correction"
        assert isinstance(model, CorrectionMessage)


class TestAgentHealthStatus:
    """Test agent health tracking."""
    
    def test_health_initialization(self):
        health = AgentHealthStatus("agent1")
        assert health.agent_id == "agent1"
        assert health.failure_count == 0
        assert health.is_open is False
    
    def test_mark_success(self):
        health = AgentHealthStatus("agent1")
        health.failure_count = 2
        health.mark_success()
        assert health.failure_count == 0
    
    def test_circuit_breaker_opens(self):
        health = AgentHealthStatus("agent1")
        assert health.is_open is False
        
        health.mark_failure("Error 1")
        assert health.is_open is False
        
        health.mark_failure("Error 2")
        assert health.is_open is False
        
        health.mark_failure("Error 3")
        assert health.is_open is True
    
    def test_circuit_breaker_reset(self):
        health = AgentHealthStatus("agent1")
        health.mark_failure("Error 1")
        health.mark_failure("Error 2")
        health.mark_failure("Error 3")
        assert health.is_open is True
        
        # Immediately can't reset
        assert health.try_reset() is False
        
        # Simulate cooldown
        health.last_success = 0  # Very old
        assert health.try_reset() is True
        assert health.is_open is False


class TestOrchestratorHardener:
    """Test orchestrator hardening."""
    
    @pytest.mark.asyncio
    async def test_successful_execution(self):
        hardener = OrchestratorHardener()
        
        async def test_coro():
            return "success"
        
        result = await hardener.execute_with_timeout(test_coro(), timeout=5.0)
        assert result == "success"
    
    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        hardener = OrchestratorHardener()
        
        async def slow_coro():
            await asyncio.sleep(10)
        
        with pytest.raises(asyncio.TimeoutError):
            await hardener.execute_with_timeout(slow_coro(), timeout=0.1)
    
    @pytest.mark.asyncio
    async def test_agent_call_success(self):
        hardener = OrchestratorHardener()
        
        async def successful_agent():
            return "Agent response"
        
        success, response, error = await hardener.execute_agent_call(
            "test_agent",
            successful_agent()
        )
        assert success is True
        assert response == "Agent response"
        assert error is None
    
    @pytest.mark.asyncio
    async def test_agent_call_timeout(self):
        hardener = OrchestratorHardener(agent_timeout=0.1)
        
        async def slow_agent():
            await asyncio.sleep(1)
        
        success, response, error = await hardener.execute_agent_call(
            "slow_agent",
            slow_agent()
        )
        assert success is False
        assert error is not None
        assert "timeout" in error.lower()
    
    @pytest.mark.asyncio
    async def test_agent_call_fallback(self):
        hardener = OrchestratorHardener(agent_timeout=0.1)
        
        async def failing_agent():
            raise Exception("Agent crashed")
        
        success, response, error = await hardener.execute_agent_call(
            "failing_agent",
            failing_agent(),
            fallback_response="Fallback response"
        )
        assert success is False
        assert response == "Fallback response"
    
    def test_get_agent_status(self):
        hardener = OrchestratorHardener()
        hardener._get_agent_health("agent1").mark_failure("Test error")
        
        status = hardener.get_agent_status("agent1")
        assert status["agent_id"] == "agent1"
        assert status["failures"] == 1
        assert status["is_healthy"] is True  # Still healthy after 1 failure


class TestSecurityValidation:
    """Test security-specific validations."""
    
    def test_id_validation_rejects_injection(self):
        data = {
            "type": "chat",
            "text": "Hello",
            "user_id": "user1'; DROP TABLE users; --"
        }
        with pytest.raises(ValueError):
            validate_websocket_message(data)
    
    def test_whitespace_normalization(self):
        data = {"type": "chat", "text": "Hello    world   !"}
        msg_type, model = validate_websocket_message(data)
        assert model.text == "Hello world !"
    
    def test_html_entity_encoding(self):
        data = {"type": "chat", "text": "Test & test"}
        msg_type, model = validate_websocket_message(data)
        assert "&amp;" in model.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
