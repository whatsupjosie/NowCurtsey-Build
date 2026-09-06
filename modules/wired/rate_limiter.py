"""
Rate limiting for PubCast AI.
Implements token bucket algorithm per user and per room.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Tuple
import logging
import asyncio

logger = logging.getLogger("pubcast.rate_limiter")


class TokenBucket:
    """Single token bucket with refill."""
    
    def __init__(self, capacity: int, refill_rate: float, refill_interval: float = 1.0):
        """
        Args:
            capacity: Max tokens in bucket
            refill_rate: Tokens added per refill interval
            refill_interval: Seconds between refills
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.refill_interval = refill_interval
        self.tokens = float(capacity)
        self.last_refill = datetime.now()
    
    def _refill(self):
        """Add tokens based on elapsed time."""
        now = datetime.now()
        elapsed = (now - self.last_refill).total_seconds()
        
        if elapsed >= self.refill_interval:
            # How many refill intervals have passed?
            intervals_passed = elapsed / self.refill_interval
            new_tokens = intervals_passed * self.refill_rate
            self.tokens = min(self.capacity, self.tokens + new_tokens)
            self.last_refill = now
    
    def consume(self, tokens: float = 1.0) -> bool:
        """
        Attempt to consume tokens.
        
        Returns:
            True if successful, False if insufficient tokens
        """
        self._refill()
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False
    
    def available(self) -> float:
        """Get current available tokens."""
        self._refill()
        return self.tokens


class RateLimiter:
    """Multi-tier rate limiter for PubCast."""
    
    def __init__(
        self,
        per_user_messages: int = 30,
        per_user_window_seconds: int = 60,
        per_room_messages: int = 100,
        per_room_window_seconds: int = 60,
        global_messages: int = 1000,
        global_window_seconds: int = 60,
    ):
        """
        Initialize rate limiter with three tiers.
        
        Args:
            per_user_messages: Max messages per user per window
            per_user_window_seconds: Time window for per-user limit
            per_room_messages: Max messages per room per window
            per_room_window_seconds: Time window for per-room limit
            global_messages: Max global messages per window
            global_window_seconds: Time window for global limit
        """
        self.per_user_messages = per_user_messages
        self.per_user_window = timedelta(seconds=per_user_window_seconds)
        self.per_room_messages = per_room_messages
        self.per_room_window = timedelta(seconds=per_room_window_seconds)
        self.global_messages = global_messages
        self.global_window = timedelta(seconds=global_window_seconds)
        
        # Token buckets: user_id -> TokenBucket
        self.user_buckets: Dict[str, TokenBucket] = {}
        
        # Token buckets: room_id -> TokenBucket
        self.room_buckets: Dict[str, TokenBucket] = {}
        
        # Global bucket
        refill_rate = global_messages / global_window_seconds
        self.global_bucket = TokenBucket(
            capacity=global_messages,
            refill_rate=refill_rate,
            refill_interval=1.0
        )
        
        # Cleanup task
        self._cleanup_task = None
        self._lock = asyncio.Lock()
    
    async def start_cleanup_task(self):
        """Start periodic cleanup of unused buckets."""
        try:
            while True:
                await asyncio.sleep(300)  # Every 5 minutes
                await self._cleanup_old_buckets()
        except asyncio.CancelledError:
            logger.info("Rate limiter cleanup stopped")
    
    async def _cleanup_old_buckets(self):
        """Remove buckets that haven't been used recently."""
        async with self._lock:
            cutoff = datetime.now() - timedelta(hours=1)
            
            # Clean user buckets
            stale_users = [
                uid for uid, bucket in self.user_buckets.items()
                if bucket.last_refill < cutoff
            ]
            for uid in stale_users:
                del self.user_buckets[uid]
                logger.debug(f"Cleaned up rate limit bucket for user {uid}")
            
            # Clean room buckets
            stale_rooms = [
                rid for rid, bucket in self.room_buckets.items()
                if bucket.last_refill < cutoff
            ]
            for rid in stale_rooms:
                del self.room_buckets[rid]
                logger.debug(f"Cleaned up rate limit bucket for room {rid}")
    
    def is_allowed(
        self,
        user_id: str,
        room_id: str = "default",
        tokens_requested: float = 1.0
    ) -> Tuple[bool, str]:
        """
        Check if user can send message.
        
        Args:
            user_id: User identifier
            room_id: Room identifier
            tokens_requested: Tokens to consume (usually 1.0)
        
        Returns:
            (allowed: bool, reason: str)
        """
        # Check global limit
        if not self.global_bucket.consume(tokens_requested):
            remaining = self.global_bucket.available()
            logger.warning(f"Global rate limit exceeded. Available: {remaining:.1f}")
            return False, "global_rate_limit"
        
        # Check per-room limit
        if room_id not in self.room_buckets:
            refill_rate = self.per_room_messages / self.per_room_window.total_seconds()
            self.room_buckets[room_id] = TokenBucket(
                capacity=self.per_room_messages,
                refill_rate=refill_rate,
                refill_interval=1.0
            )
        
        if not self.room_buckets[room_id].consume(tokens_requested):
            remaining = self.room_buckets[room_id].available()
            logger.warning(
                f"Room {room_id} rate limit exceeded. Available: {remaining:.1f}"
            )
            return False, "room_rate_limit"
        
        # Check per-user limit
        if user_id not in self.user_buckets:
            refill_rate = self.per_user_messages / self.per_user_window.total_seconds()
            self.user_buckets[user_id] = TokenBucket(
                capacity=self.per_user_messages,
                refill_rate=refill_rate,
                refill_interval=1.0
            )
        
        if not self.user_buckets[user_id].consume(tokens_requested):
            remaining = self.user_buckets[user_id].available()
            logger.warning(
                f"User {user_id} rate limit exceeded. Available: {remaining:.1f}"
            )
            return False, "user_rate_limit"
        
        return True, ""
    
    def get_user_status(self, user_id: str) -> Dict[str, float]:
        """Get current token availability for user."""
        if user_id not in self.user_buckets:
            return {"available": float(self.per_user_messages), "capacity": self.per_user_messages}
        
        bucket = self.user_buckets[user_id]
        return {
            "available": bucket.available(),
            "capacity": bucket.capacity
        }
    
    def reset_user(self, user_id: str):
        """Reset rate limit for a user (admin operation)."""
        if user_id in self.user_buckets:
            del self.user_buckets[user_id]
            logger.info(f"Rate limit reset for user {user_id}")
    
    def reset_room(self, room_id: str):
        """Reset rate limit for a room (admin operation)."""
        if room_id in self.room_buckets:
            del self.room_buckets[room_id]
            logger.info(f"Rate limit reset for room {room_id}")
