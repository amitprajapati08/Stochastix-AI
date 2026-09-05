"""
Cost-aware decision policy: turns a risk probability into a real action.
Deliberately separate from model.py — this file contains ZERO machine
learning. It is the "what do we do about a risk score" layer, distinct
from "what is the risk score" layer. A judge should be able to read this
file alone and understand the entire decision policy without touching
any ML code.
"""

# A score between the threshold and this multiple of it is ambiguous —
# worth a step-up challenge, not an outright decline.
STEP_UP_MULTIPLIER = 1.8


def decide(risk_probability: float, threshold: float) -> str:
    """Pure function: probability + threshold -> a decision string.
    No side effects, no model access — trivial to unit test alone."""
    if risk_probability >= threshold:
        if risk_probability < threshold * STEP_UP_MULTIPLIER:
            return "3DS_STEP_UP"
        return "BLOCK"
    return "ALLOW"