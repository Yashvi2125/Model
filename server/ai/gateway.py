"""Central AI Gateway for MileMates.

Provides unified routing, token-bucket rate limiting, priority queuing with starvation protection,
in-memory call metering, and error classification.

Setting AI_GATEWAY_ENABLED=false restores the legacy direct path completely.
"""
import asyncio
import logging
import os
import re
import time
from typing import Any, Callable, Optional

log = logging.getLogger("tripmate.ai.gateway")

# Feature priority constants
PRIORITY_URGENT = 1       # Itinerary planning, @ai chat replies
PRIORITY_INTERACTIVE = 2  # Conflicts tab analysis, budget extraction, merge preferences
PRIORITY_BACKGROUND = 3   # Chat preference auto-extraction, chat conflict scan
PRIORITY_DEFERRABLE = 4   # Map place validation
PRIORITY_SKIPPABLE = 5    # Map coordinate approximation

# Precise error classification patterns using exact word boundaries
# Prevents false positive substring matches on words like "generate", "accurate", "operate"
RE_QUOTA_ERROR = re.compile(r"\b(429|resource_exhausted|quota_exceeded)\b", re.IGNORECASE)
RE_OVERLOAD_ERROR = re.compile(r"\b(500|502|503|504|unavailable|overloaded|service_unavailable)\b", re.IGNORECASE)
RE_RETRY_DELAY = re.compile(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)\s*s?", re.IGNORECASE)
RE_RETRY_AFTER = re.compile(r"retry_after['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)", re.IGNORECASE)
RE_TRY_AGAIN_IN = re.compile(r"try again in\s+(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


class GatewayError(Exception):
    """Base error raised by the AI Gateway."""
    pass


class QueueTimeoutError(GatewayError):
    """Raised when a queued request exceeds its priority-level max wait time."""
    pass


class QuotaSkippedError(GatewayError):
    """Raised when a skippable/deferrable task is skipped to conserve AI quota."""
    pass


def parse_retry_delay(exc: Exception) -> Optional[float]:
    """Extract retry delay in seconds from exception string or details if present."""
    text = str(exc)
    for pat in (RE_RETRY_DELAY, RE_RETRY_AFTER, RE_TRY_AGAIN_IN):
        m = pat.search(text)
        if m:
            try:
                return float(m.group(1))
            except (ValueError, TypeError):
                pass
    return None


def is_rate_limit_error(exc: Exception) -> bool:
    """Check if the error is 429 or RESOURCE_EXHAUSTED using word boundaries."""
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status_code == 429:
        return True
    text = str(exc)
    return bool(RE_QUOTA_ERROR.search(text))


def is_overload_error(exc: Exception) -> bool:
    """Check if the error is a 503, 500, or temporary server overload."""
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status_code in (500, 502, 503, 504):
        return True
    text = str(exc)
    if any(k in text.lower() for k in ("timed out", "timeout", "connection error", "connection reset")):
        return True
    return bool(RE_OVERLOAD_ERROR.search(text))


def is_daily_quota_error(exc: Exception) -> bool:
    """Check if the error is due to daily quota exhaustion (requests per day)."""
    text = str(exc).lower()
    if any(k in text for k in ("per day", "requests per day", "daily", "day limit", "free_tier_requests_per_day", "per_day")):
        return True
    delay = parse_retry_delay(exc)
    if delay is not None and delay > 300:
        return True
    return False


class TokenBucket:
    """Per-model token bucket rate limiter."""

    def __init__(self, capacity: float, refill_rate: float):
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)  # tokens per second
        self.tokens = float(capacity)
        self.last_update = time.time()
        self.cooldown_until = 0.0

    def refill(self, now: Optional[float] = None) -> None:
        now = now or time.time()
        elapsed = now - self.last_update
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + (elapsed * self.refill_rate))
            self.last_update = now

    def in_cooldown(self, now: Optional[float] = None) -> bool:
        now = now or time.time()
        return now < self.cooldown_until

    def available(self, now: Optional[float] = None) -> float:
        now = now or time.time()
        if self.in_cooldown(now):
            return 0.0
        self.refill(now)
        return self.tokens

    def consume(self, amount: float = 1.0, now: Optional[float] = None) -> bool:
        now = now or time.time()
        if self.in_cooldown(now):
            return False
        self.refill(now)
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False

    def penalize(self, delay_seconds: float) -> None:
        now = time.time()
        self.cooldown_until = max(self.cooldown_until, now + delay_seconds)
        self.tokens = 0.0


class QueueWaiter:
    """Represents a request waiting in the priority queue."""

    def __init__(
        self,
        priority: int,
        model: str,
        feature: str,
        timeout: float,
        status_callback: Optional[Callable[[str], None]] = None,
    ):
        self.priority = priority
        self.model = model
        self.feature = feature
        self.timeout = timeout
        self.status_callback = status_callback
        self.enqueue_time = time.time()
        self.future: asyncio.Future[bool] = asyncio.Future()

    @property
    def effective_priority(self) -> float:
        """Starvation protection: aged items gain priority boost."""
        age = time.time() - self.enqueue_time
        return self.priority - (age * 0.05)


class AIGateway:
    """Central AI Gateway with token bucket rate limiting, priority queue, and metering."""

    def __init__(self):
        self.enabled = os.getenv("AI_GATEWAY_ENABLED", "true").lower() in ("true", "1", "yes")
        self.rpm_limit = int(os.getenv("AI_RPM_PER_MODEL", "9"))
        self.daily_budget = int(os.getenv("AI_DAILY_BUDGET_PER_MODEL", "500"))

        # In-memory metrics (advisory, reset on process restart)
        self.total_requests = 0
        self.requests_by_feature: dict[str, int] = {}
        self.requests_by_model: dict[str, int] = {}
        self.requests_by_status: dict[str, int] = {}
        self.cooldowns: dict[str, float] = {}  # model_name -> expiration epoch seconds
        self._sliding_window_timestamps: list[float] = []

        # Token buckets: model_name -> TokenBucket
        self._buckets: dict[str, TokenBucket] = {}
        self._queue: list[QueueWaiter] = []
        self._queue_lock: Optional[asyncio.Lock] = None

    def is_enabled(self) -> bool:
        return self.enabled

    def reset(self):
        """Reset in-memory buckets, cooldowns, and timestamps (useful for tests)."""
        self.total_requests = 0
        self.requests_by_feature.clear()
        self.requests_by_model.clear()
        self.requests_by_status.clear()
        self.cooldowns.clear()
        self._sliding_window_timestamps.clear()
        self._buckets.clear()
        self._queue.clear()

    def _get_bucket(self, model: str) -> TokenBucket:
        if model not in self._buckets:
            refill_rate = self.rpm_limit / 60.0
            self._buckets[model] = TokenBucket(capacity=self.rpm_limit, refill_rate=refill_rate)
        return self._buckets[model]

    def record_call(self, feature: str, model: str, status: int | str):
        now = time.time()
        self.total_requests += 1
        self.requests_by_feature[feature] = self.requests_by_feature.get(feature, 0) + 1
        self.requests_by_model[model] = self.requests_by_model.get(model, 0) + 1
        status_key = str(status)
        self.requests_by_status[status_key] = self.requests_by_status.get(status_key, 0) + 1
        self._sliding_window_timestamps.append(now)
        # Purge timestamps older than 60s
        self._sliding_window_timestamps = [t for t in self._sliding_window_timestamps if now - t < 60]

    def set_cooldown(self, model: str, seconds: float):
        now = time.time()
        self.cooldowns[model] = now + seconds
        bucket = self._get_bucket(model)
        bucket.penalize(seconds)

    def learn_429(self, model: str, retry_delay: Optional[float] = None):
        """Learn backoff from a 429 response retryDelay."""
        delay = retry_delay if (retry_delay and retry_delay > 0) else 60.0
        log.warning("Gateway learned 429 rate limit for '%s': enforcing %s delay", model, delay)
        self.set_cooldown(model, delay)

    def is_model_available(self, model: str) -> bool:
        bucket = self._get_bucket(model)
        if bucket.in_cooldown():
            return False
        exp = self.cooldowns.get(model)
        if exp and time.time() < exp:
            return False
        return True

    def is_budget_low(self, model: Optional[str] = None) -> bool:
        """Check if rate limit or daily budget is low."""
        if not self.enabled:
            return False
        if model:
            bucket = self._get_bucket(model)
            if bucket.available() < 2.0 or bucket.in_cooldown():
                return True
        recent_count = len([t for t in self._sliding_window_timestamps if time.time() - t < 60])
        return recent_count >= (self.rpm_limit - 1)

    def should_skip_optional(self, priority: int, model: Optional[str] = None) -> bool:
        """Determine whether an optional/skippable AI call should be skipped."""
        if not self.enabled:
            return False
        if priority >= PRIORITY_SKIPPABLE:
            return self.is_budget_low(model)
        return False

    async def acquire_slot(
        self,
        model: str,
        priority: int = PRIORITY_URGENT,
        feature: str = "single_turn",
        timeout: Optional[float] = None,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Acquire a token from the rate limiter via the priority queue.

        Implements:
        - Max-wait thresholds per priority (background dropped after ~60s).
        - Starvation protection (wait time boosts priority).
        - Status callback for user-facing waiting states ('Waiting in queue...').
        """
        if not self.enabled:
            return

        now = time.time()
        bucket = self._get_bucket(model)

        # 1. Immediate skip check for Priority 5 (skippable fallback)
        if priority >= PRIORITY_SKIPPABLE and self.is_budget_low(model):
            raise QuotaSkippedError("Skipped to save AI quota (will retry in background)")

        # 2. Fast path: if no queue and bucket has available token immediately
        if not self._queue and not bucket.in_cooldown(now) and bucket.consume(1.0, now):
            return

        # Determine maximum wait based on priority
        user_timeout = timeout or 180.0
        if priority == PRIORITY_URGENT:
            max_wait = user_timeout
        elif priority == PRIORITY_INTERACTIVE:
            max_wait = min(user_timeout, 45.0)
        elif priority in (PRIORITY_BACKGROUND, PRIORITY_DEFERRABLE):
            max_wait = min(user_timeout, 60.0)
        else:
            max_wait = min(user_timeout, 5.0)

        waiter = QueueWaiter(
            priority=priority,
            model=model,
            feature=feature,
            timeout=max_wait,
            status_callback=status_callback,
        )

        if self._queue_lock is None:
            self._queue_lock = asyncio.Lock()

        async with self._queue_lock:
            self._queue.append(waiter)

        start_wait = time.time()
        if status_callback and priority == PRIORITY_URGENT:
            status_callback("Waiting in queue…")

        try:
            while True:
                elapsed = time.time() - start_wait
                remaining = max_wait - elapsed
                if remaining <= 0:
                    if priority in (PRIORITY_BACKGROUND, PRIORITY_DEFERRABLE, PRIORITY_SKIPPABLE):
                        raise QueueTimeoutError(f"Background task '{feature}' dropped after {round(elapsed)}s in queue")
                    else:
                        raise QueueTimeoutError(f"Request '{feature}' timed out after {round(elapsed)}s in queue")

                now = time.time()
                # Check if this waiter is eligible to be served next
                async with self._queue_lock:
                    # Sort by effective_priority (lowest number is highest priority, aging boosts priority)
                    self._queue.sort(key=lambda w: w.effective_priority)
                    is_head = (self._queue and self._queue[0] is waiter)

                    if is_head and not bucket.in_cooldown(now) and bucket.consume(1.0, now):
                        self._queue.remove(waiter)
                        return

                # Calculate how long to sleep before next retry
                if bucket.in_cooldown(now):
                    sleep_time = min(remaining, max(0.5, bucket.cooldown_until - now))
                else:
                    needed = max(0.0, 1.0 - bucket.tokens)
                    sleep_time = min(remaining, max(0.2, (needed / bucket.refill_rate) if bucket.refill_rate > 0 else 1.0))

                if status_callback and priority == PRIORITY_URGENT and elapsed > 2.0:
                    status_callback(f"Waiting in queue ({round(elapsed)}s)…")

                await asyncio.sleep(min(sleep_time, 2.0))

        finally:
            if self._queue_lock:
                async with self._queue_lock:
                    if waiter in self._queue:
                        self._queue.remove(waiter)

    def get_usage(self) -> dict[str, Any]:
        """Return read-only metrics without any prompts, user content, or API keys."""
        now = time.time()
        active_cooldowns = {
            m: round(exp - now, 1)
            for m, exp in self.cooldowns.items()
            if exp > now
        }
        recent_window_count = len([t for t in self._sliding_window_timestamps if now - t < 60])
        queue_count = len(self._queue)
        return {
            "gateway_enabled": self.enabled,
            "rpm_limit_per_model": self.rpm_limit,
            "daily_budget_advisory": self.daily_budget,
            "current_minute_requests": recent_window_count,
            "queued_requests": queue_count,
            "total_requests": self.total_requests,
            "requests_by_feature": dict(self.requests_by_feature),
            "requests_by_model": dict(self.requests_by_model),
            "requests_by_status": dict(self.requests_by_status),
            "active_cooldowns_remaining_seconds": active_cooldowns,
            "note": "Counters are in-memory and advisory for this container process only; reset on restart.",
        }


# Global singleton gateway
gateway = AIGateway()
