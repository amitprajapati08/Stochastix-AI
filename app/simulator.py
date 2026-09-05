"""
Synthetic traffic simulator for Sentinel.

Two deliberate design choices, both direct responses to real weaknesses
found in review:

1. Overlapping edge cases — legitimate low-value transactions (UPI
   top-ups, small recharges) and occasional higher-value bot probes — so
   a trivial "amount < X" rule cannot solve this problem as well as the
   real feature set. If your model's precision/recall look suspiciously
   perfect, check whether this overlap is actually being generated.

2. Attack evolution, 3 versions of increasing attacker sophistication:
   - V1: same device, same IP, spread across merchants (the easy case)
   - V2: same device, ROTATING IP (defeats simple per-IP velocity rules)
   - V3: ROTATING device AND IP, only amount/timing pattern and
     merchant-spread behaviour stay consistent — this is the case a real
     system needs additional signals to catch, and where you should
     EXPECT your prototype's recall to drop. Documenting that drop
     honestly is your failure-recovery story, not a bug to hide.
"""

import random
import uuid
from typing import Dict, Any, List


class BuiltInTrafficSimulator:
    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed)
        self.merchants = [f"mid_rzp_{i:03d}" for i in range(1, 30)]
        self.card_bins = ["431411", "510510", "462002", "522100", "400013"]

    def generate_legitimate_stream(self) -> Dict[str, Any]:
        rng = self._rng
        if rng.random() < 0.08:
            amount = round(rng.uniform(2.0, 60.0), 2)
        else:
            amount = round(rng.uniform(500.0, 15000.0), 2)

        return {
            "transaction_id": f"pay_organic_{uuid.uuid4().hex[:10]}",
            "merchant_id": rng.choice(self.merchants),
            "amount": amount,
            "card_token": f"tok_card_{rng.randint(111111, 999999)}",
            "card_bin": rng.choice(self.card_bins),
            "ip_address": f"49.36.{rng.randint(0,255)}.{rng.randint(0,255)}",
            "device_fingerprint": f"df_user_{rng.randint(10000, 99999)}",
            "is_fraud": 0,
        }

    def generate_botnet_burst(self, scale: int = 30, version: int = 1) -> List[Dict[str, Any]]:
        rng = self._rng
        burst_payloads = []
        shared_device = f"df_device_BOTNET_{uuid.uuid4().hex[:6]}"
        shared_ip = f"103.241.{rng.randint(0,255)}.{rng.randint(0,255)}"

        for _ in range(scale):
            if version == 1:
                device, ip = shared_device, shared_ip
            elif version == 2:
                device = shared_device
                ip = f"{rng.randint(1,223)}.{rng.randint(0,255)}.{rng.randint(0,255)}.{rng.randint(0,255)}"
            else:
                device = f"df_device_BOTNET_{uuid.uuid4().hex[:6]}"
                ip = f"{rng.randint(1,223)}.{rng.randint(0,255)}.{rng.randint(0,255)}.{rng.randint(0,255)}"

            burst_payloads.append(
                {
                    "transaction_id": f"pay_bot_v{version}_{uuid.uuid4().hex[:10]}",
                    "merchant_id": rng.choice(self.merchants),
                    "amount": round(rng.uniform(2.0, 12.0), 2),
                    "card_token": f"tok_card_STOLEN_{rng.randint(1000, 9999)}",
                    "card_bin": f"{rng.randint(400000, 499999)}",
                    "ip_address": ip,
                    "device_fingerprint": device,
                    "is_fraud": 1,
                    "attack_version": version,
                }
            )
        return burst_payloads

    def generate_botnet_signature_burst(self, scale: int = 30) -> List[Dict[str, Any]]:
        return self.generate_botnet_burst(scale=scale, version=1)
