"""
Baseline: the kind of rule a SINGLE merchant could write with only their
own transaction history — no cross-merchant visibility at all. This is
the thing Sentinel needs to beat, and the comparison against it is your
headline experiment (does cross-merchant visibility actually help?).

Deliberately dumb on purpose: a real merchant-local system might be a bit
smarter than this, but this represents the ceiling of what's possible
WITHOUT seeing across merchants — which is exactly the constraint we're
arguing matters.
"""

from typing import Dict, Any


class MerchantLocalBaseline:
    """Flags a transaction if amount is very low AND this device has
    made several transactions at THIS merchant recently. Notice what
    it cannot see: how many OTHER merchants this device just hit —
    that's the whole point."""

    def __init__(self, low_amount_threshold: float = 15.0, txn_count_threshold: int = 4):
        self.low_amount_threshold = low_amount_threshold
        self.txn_count_threshold = txn_count_threshold
        # merchant-scoped only: (merchant_id, device_fingerprint) -> count
        self._local_counts: Dict[tuple, int] = {}

    def score_transaction(self, payload: Dict[str, Any]) -> str:
        key = (payload["merchant_id"], payload["device_fingerprint"])
        self._local_counts[key] = self._local_counts.get(key, 0) + 1

        if (
            payload["amount"] <= self.low_amount_threshold
            and self._local_counts[key] >= self.txn_count_threshold
        ):
            return "BLOCK"
        return "ALLOW"
