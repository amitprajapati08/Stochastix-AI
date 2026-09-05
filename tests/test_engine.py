"""
Proves the merchant_diversity_device fix: a merchant seen OUTSIDE the
rolling window must not be counted, even though the underlying Redis key
itself is still alive (TTL not yet expired). Before the fix, this test
would have failed — a plain SET with a whole-key TTL cannot age out
individual members.
"""
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine import SentinelRedisEngine


def make_event(transaction_id, merchant_id, device_fingerprint="df_window_test"):
    return {
        "transaction_id": transaction_id,
        "merchant_id": merchant_id,
        "amount": 10.0,
        "card_token": "tok_window_test",
        "card_bin": "431411",
        "ip_address": "10.1.1.1",
        "device_fingerprint": device_fingerprint,
    }


def test_merchant_ages_out_of_rolling_window():
    engine = SentinelRedisEngine(window_ms=300)
    engine.client.flushdb()

    f1 = engine.extract_realtime_features(make_event("t1", "merchant_A"))
    assert f1["merchant_diversity_device"] == 1, f"expected 1, got {f1['merchant_diversity_device']}"

    f2 = engine.extract_realtime_features(make_event("t2", "merchant_B"))
    assert f2["merchant_diversity_device"] == 2, f"expected 2, got {f2['merchant_diversity_device']}"

    time.sleep(0.4)

    f3 = engine.extract_realtime_features(make_event("t3", "merchant_C"))
    assert f3["merchant_diversity_device"] == 1, (
        f"expected 1 (only merchant_C, A and B should have aged out), "
        f"got {f3['merchant_diversity_device']} — the rolling window is not evicting stale merchants"
    )

    print("PASS: merchant_diversity_device correctly evicts merchants outside the rolling window")


def test_repeated_merchant_refreshes_not_duplicates():
    engine = SentinelRedisEngine(window_ms=300)
    engine.client.flushdb()

    engine.extract_realtime_features(make_event("t1", "merchant_A"))
    f2 = engine.extract_realtime_features(make_event("t2", "merchant_A"))
    assert f2["merchant_diversity_device"] == 1, (
        f"expected 1 (same merchant twice should not double-count), got {f2['merchant_diversity_device']}"
    )
    print("PASS: repeated visits to the same merchant do not inflate the diversity count")


if __name__ == "__main__":
    test_merchant_ages_out_of_rolling_window()
    test_repeated_merchant_refreshes_not_duplicates()
    print("\nAll tests passed.")