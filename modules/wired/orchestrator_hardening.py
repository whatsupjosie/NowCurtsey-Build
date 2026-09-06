"""
Orchestrator hardening for production resilience.
Adds streaming timeout, error recovery, and circuit breaker pattern.
"""

import asyncio
import logging
import time
from typing import AsyncIterator, Optional, List
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger("pubcast.orchestrator_hardening")


@dataclass
class AgentHealthStatus:
    """Track agent health for circuit breaker."""
    agent_id: str
    last_success: float = 0.0
    failure_count: int = 0
    is_open: bool = False
    last_error: Optional[str] = None
    
    def mark_success(self):
        """Record successful agent call."""
        self.last_success = time.time()
        self.failure_count = 0
        self.is_open = False
    
    def mark_failure(self, error: str):
        """Record agent failure."""
        self.failure_count += 1
        self.last_error = error
        # Open circuit after 3 consecutive failures
        if self.failure_count >= 3:
            self.is_open = True
            logger.warning(
                f"Circuit breaker opened for agent {self.agent_id} "
                f"after {self.failure_count} failures: {error}"
            )
    
    def try_reset(self) -> bool:
        """Attempt to reset circuit after cooldown."""
        if not self.is_open:
            return True
        
        cooldown = 60  # seconds
        elapsed = time.time() - self.last_success
        if elapsed > cooldown:
            logger.info(f"Circuit breaker attempting reset for {self.agent_id}")
            self.is_open = False
            self.failure_count = 0
            return True
        return False


class OrchestratorHardener:
    """
    Hardening layer for async orchestration.
    Handles timeouts, errors, and circuit breaking.
    """
    
    def __init__(
        self,
        orchestration_timeout: float = 30.0,
        agent_timeout: float = 15.0,
        max_agent_failures: int = 3,
        circuit_breaker_cooldown: float = 60.0,
    ):
        """
        Args:
            orchestration_timeout: Total timeout for entire message processing
            agent_timeout: Per-agent timeout
            max_agent_failures: Failures before circuit break
            circuit_breaker_cooldown: Seconds before retry after circuit break
        """
        self.orchestration_timeout = orchestration_timeout
        self.agent_timeout = agent_timeout
        self.max_agent_failures = max_agent_failures
        self.circuit_breaker_cooldown = circuit_breaker_cooldown
        self.agent_health: dict[str, AgentHealthStatus] = {}
    
    def _get_agent_health(self, agent_id: str) -> AgentHealthStatus:
        """Get or create agent health tracker."""
        if agent_id not in self.agent_health:
            self.agent_health[agent_id] = AgentHealthStatus(agent_id)
        return self.agent_health[agent_id]
    
    async def execute_with_timeout(
        self,
        coro,
        timeout: float,
        timeout_msg: str = "Operation timed out"
    ):
        """
        Execute coroutine with timeout.
        
        Raises:
            asyncio.TimeoutError: If timeout exceeded
        """
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            logger.error(f"Timeout after {timeout}s: {timeout_msg}")
            raise
    
    async def execute_agent_call(
        self,
        agent_id: str,
        call_coro,
        fallback_response: Optional[str] = None
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Execute agent call with timeout, error handling, and circuit breaker.
        
        Returns:
            (success: bool, response: Optional[str], error: Optional[str])
        """
        health = self._get_agent_health(agent_id)
        
        # Check circuit breaker
        if health.is_open and not health.try_reset():
            msg = f"Agent {agent_id} circuit breaker open (cooldown: {self.circuit_breaker_cooldown}s)"
            logger.warning(msg)
            return False, fallback_response, msg
        
        try:
            logger.debug(f"Executing agent {agent_id} with timeout {self.agent_timeout}s")
            
            response = await self.execute_with_timeout(
                call_coro,
                timeout=self.agent_timeout,
                timeout_msg=f"Agent {agent_id} did not respond in time"
            )
            
            health.mark_success()
            logger.debug(f"Agent {agent_id} completed successfully")
            return True, response, None
            
        except asyncio.TimeoutError as e:
            error_msg = f"Agent {agent_id} timeout"
            health.mark_failure(error_msg)
            logger.error(error_msg)
            return False, fallback_response, error_msg
            
        except Exception as e:
            error_msg = f"Agent {agent_id} error: {str(e)}"
            health.mark_failure(error_msg)
            logger.error(error_msg, exc_info=True)
            return False, fallback_response, error_msg
    
    async def execute_orchestration(
        self,
        orchestration_coro,
        error_handler = None
    ):
        """
        Execute full orchestration with top-level timeout.
        
        Args:
            orchestration_coro: The async generator or coroutine to execute
            error_handler: Callable to handle timeout/error
        """
        try:
            logger.debug(f"Starting orchestration with {self.orchestration_timeout}s timeout")
            
            await self.execute_with_timeout(
                orchestration_coro,
                timeout=self.orchestration_timeout,
                timeout_msg="Orchestration timeout"
            )
            
        except asyncio.TimeoutError:
            logger.error("Orchestration timed out")
            if error_handler:
                await error_handler("timeout")
            raise
        except Exception as e:
            logger.error(f"Orchestration error: {str(e)}", exc_info=True)
            if error_handler:
                await error_handler(str(e))
            raise
    
    def get_agent_status(self, agent_id: str) -> dict:
        """Get current status of an agent."""
        health = self._get_agent_health(agent_id)
        return {
            "agent_id": agent_id,
            "is_healthy": not health.is_open,
            "failures": health.failure_count,
            "last_error": health.last_error,
            "circuit_open": health.is_open,
        }
    
    def get_all_agent_status(self) -> List[dict]:
        """Get status of all agents."""
        return [self.get_agent_status(aid) for aid in self.agent_health.keys()]
    
    def reset_agent(self, agent_id: str):
        """Reset agent health (admin operation)."""
        if agent_id in self.agent_health:
            self.agent_health[agent_id] = AgentHealthStatus(agent_id)
            logger.info(f"Health reset for agent {agent_id}")


class StreamingErrorRecovery:
    """
    Wrapper for streaming responses to handle mid-stream failures.
    Aggregates chunks and provides retry capability.
    """
    
    def __init__(self, max_chunk_size: int = 1024, max_retries: int = 1):
        self.max_chunk_size = max_chunk_size
        self.max_retries = max_retries
        self.chunks: List[str] = []
        self.errors: List[str] = []
    
    async def stream_with_recovery(
        self,
        stream_coro_factory,
        retry_on_error: bool = True
    ) -> AsyncIterator[str]:
        """
        Stream chunks with recovery capability.
        
        Args:
            stream_coro_factory: Callable that returns a new streaming coroutine
            retry_on_error: Whether to retry on error
        
        Yields:
            Chunks of streamed data
        """
        retries_left = self.max_retries if retry_on_error else 0
        
        while True:
            try:
                chunk_count = 0
                async for chunk in stream_coro_factory():
                    if len(chunk) > self.max_chunk_size:
                        logger.warning(
                            f"Oversized chunk received: {len(chunk)} > {self.max_chunk_size}"
                        )
                        chunk = chunk[:self.max_chunk_size]
                    
                    self.chunks.append(chunk)
                    chunk_count += 1
                    yield chunk
                
                logger.debug(f"Stream completed with {chunk_count} chunks")
                break
                
            except Exception as e:
                error_msg = str(e)
                self.errors.append(error_msg)
                logger.error(f"Stream error: {error_msg}")
                
                if retries_left > 0:
                    logger.info(f"Retrying stream ({retries_left} retries left)")
                    retries_left -= 1
                    self.chunks = []  # Reset for retry
                    await asyncio.sleep(1)  # Backoff
                else:
                    logger.error("Stream failed after retries")
                    raise
    
    def get_full_response(self) -> str:
        """Get aggregated chunks."""
        return ''.join(self.chunks)
