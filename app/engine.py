"""
Sentinel Redis Engine — deterministic, sub-5ms cross-merchant velocity features.

Design note (AI judgment): this file deliberately contains ZERO machine
learning. Rolling transaction counts per card/IP/device, and the number of
distinct merchants a device has touched in the window, are EXACT
quantities — there is nothing to predict. Using a model here would only
add latency and non-determinism. Redis sorted sets (ZSETs) give us an
atomic, O(log N) "remove old, add new, count" pipeline that runs in low
single-digit milliseconds, which is what actually protects the gateway's SLA.
"""

import time
from typing import Dict, Any
import redis

# TTL on the raw window keys. Must be >= window_ms so an active key never
# expires out from under a legitimate in-progress window, but short enough
# that a card/IP/device that goes quiet stops holding memory forever.
KEY_TTL_SECONDS = 120


class SentinelRedisEngine:
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0, window_ms: int = 60000):
        self.client = redis.Redis(
            host=host, port=port, db=db, decode_responses=True, socket_timeout=1
        )
        self.window_ms = window_ms  # rolling window, default 60 seconds

    def extract_realtime_features(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        now_ms = int(time.time() * 1000)
        cutoff_ms = now_ms - self.window_ms

        card_token = payload["card_token"]
        ip_addr = payload["ip_address"]
        device_fg = payload["device_fingerprint"]

        card_key = f"sentinel:card:{card_token}"
        ip_key = f"sentinel:ip:{ip_addr}"
        device_key = f"sentinel:device:{device_fg}"
        merchant_key = f"sentinel:meta:merchant:{device_fg}"

        pipe = self.client.pipeline()

        pipe.zremrangebyscore(card_key, "-inf", cutoff_ms)
        pipe.zremrangebyscore(ip_key, "-inf", cutoff_ms)
        pipe.zremrangebyscore(device_key, "-inf", cutoff_ms)

        pipe.zadd(card_key, {f"{now_ms}:{payload['transaction_id']}": now_ms})
        pipe.zadd(ip_key, {f"{now_ms}:{payload['transaction_id']}": now_ms})
        pipe.zadd(device_key, {f"{now_ms}:{payload['transaction_id']}": now_ms})

        pipe.zcard(card_key)
        pipe.zcard(ip_key)
        pipe.zcard(device_key)

        # merchant_diversity_device — FIXED: this used to be a plain SET
        # with a whole-key TTL, meaning individual merchants never aged
        # out of the 60s window. Now it's a sorted set keyed by
        # merchant_id with score = last-seen timestamp: ZADD naturally
        # updates a repeated merchant's timestamp, and
        # ZREMRANGEBYSCORE evicts merchants not seen within window_ms,
        # exactly like the velocity ZSETs above.
        pipe.zremrangebyscore(merchant_key, "-inf", cutoff_ms)
        pipe.zadd(merchant_key, {payload["merchant_id"]: now_ms})
        pipe.zcard(merchant_key)

        pipe.expire(card_key, KEY_TTL_SECONDS)
        pipe.expire(ip_key, KEY_TTL_SECONDS)
        pipe.expire(device_key, KEY_TTL_SECONDS)
        pipe.expire(merchant_key, KEY_TTL_SECONDS)

        results = pipe.execute()

        return {
            "amount": float(payload["amount"]),
            "velocity_60s_card": int(results[6]),
            "velocity_60s_ip": int(results[7]),
            "velocity_60s_device": int(results[8]),
            "merchant_diversity_device": int(results[11]),
        }