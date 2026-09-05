"""
Agentic Risk Guardrail — the AI Investigator.

AI judgment split, deliberately:
  - WHAT changes (the threshold delta) is a small, bounded, deterministic
    rule. Fast, auditable, never talked into an unsafe state by a bad LLM
    response — see AsymmetricalSentinelModel.adjust_threshold.
  - WHY it changed, and what a human should know, is investigated by an
    LLM — but only over STRUCTURED EVIDENCE pulled from two sources: the
    current burst (what just happened) and the permanent audit trail
    (what this device has done, ever). The LLM is explicitly instructed
    to cite only this evidence, never invent anything.
  - The LLM's output is a RECOMMENDATION for a human analyst. The
    authoritative decision (threshold change) already happened before
    the LLM is even called — this is investigation, not decision-making.

If ANTHROPIC_API_KEY is not set, the agent still recalibrates safely and
falls back to a templated report — the safety-critical path never
depends on an external API call succeeding.
"""

import os
import logging
from typing import List, Dict, Any, Optional
from collections import Counter
from app.model import AsymmetricalSentinelModel
from app import audit_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sentinel.agent_guard")


class AgenticRiskGuardrail:
    def __init__(self, model_engine: AsymmetricalSentinelModel, trigger_count: int = 10):
        self.model_engine = model_engine
        self.anomaly_buffer: List[Dict[str, Any]] = []
        self.trigger_count = trigger_count
        self.incident_log: List[Dict[str, Any]] = []

        self._client = None
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=api_key)
            except Exception as err:
                logger.warning("Anthropic client unavailable, falling back to templated notes: %s", err)

    def ingest_webhook_feedback(self, event_type: str, data: Dict[str, Any]):
        if event_type == "payment.failed" and data.get("reason") == "CARD_TESTING_SUSPECTED":
            self.anomaly_buffer.append(data)
            if len(self.anomaly_buffer) >= self.trigger_count:
                self.execute_autonomous_policy_recalibration()

    def _summarize_cluster(self) -> Dict[str, Any]:
        devices = Counter(e.get("device_fingerprint") for e in self.anomaly_buffer)
        ips = Counter(e.get("ip_address") for e in self.anomaly_buffer)
        merchants = {e.get("merchant_id") for e in self.anomaly_buffer}
        amounts = [e.get("amount", 0) for e in self.anomaly_buffer]
        dominant_device = devices.most_common(1)[0][0] if devices else None
        return {
            "event_count": len(self.anomaly_buffer),
            "dominant_device": dominant_device,
            "dominant_ip": ips.most_common(1)[0] if ips else None,
            "distinct_merchants_hit": len(merchants),
            "amount_range": (min(amounts), max(amounts)) if amounts else (0, 0),
        }

    def _gather_evidence(self, cluster: Dict[str, Any]) -> Dict[str, Any]:
        """Structured evidence object: current burst + permanent history.
        This is the ONLY thing the LLM is allowed to reference."""
        evidence = {"current_burst": cluster, "device_history": None}
        device = cluster.get("dominant_device")
        if device:
            try:
                with audit_db.get_conn() as conn:
                    evidence["device_history"] = audit_db.get_device_investigation_evidence(conn, device)
            except Exception as err:
                logger.warning("Could not fetch device history for investigation: %s", err)
        return evidence

    def _generate_incident_note(self, evidence: Dict[str, Any], old_threshold: float, new_threshold: float) -> str:
        cluster = evidence["current_burst"]
        history = evidence["device_history"]

        if self._client is None:
            history_line = (
                f"Lifetime: {history['lifetime_transaction_count']} txns across "
                f"{history['lifetime_distinct_merchants']} merchants, {history['lifetime_blocks']} prior blocks."
                if history else "No lifetime history available."
            )
            return (
                f"[templated] Evidence: {cluster['event_count']} suspected card-testing events across "
                f"{cluster['distinct_merchants_hit']} merchants, low-value range {cluster['amount_range']}. "
                f"{history_line} Threshold tightened {old_threshold:.3f} -> {new_threshold:.3f}. "
                f"Hypothesis: coordinated card-testing burst. Recommended action: review flagged device manually."
            )
        try:
            prompt = (
                "You are a fraud investigation assistant. You will be given STRUCTURED EVIDENCE "
                "only — you must not reference anything outside it, and you must not invent evidence.\n\n"
                f"Current burst evidence: {cluster}\n"
                f"Device lifetime history (from the permanent audit trail): {history}\n"
                f"The system tightened its decision threshold from {old_threshold:.3f} to {new_threshold:.3f}.\n\n"
                "Write a short investigation report for a human risk analyst with exactly these "
                "three labeled sections, each 1-2 sentences:\n"
                "Evidence: (cite only the numbers given above)\n"
                "Hypothesis: (your best explanation, clearly labeled as a hypothesis, not a certainty)\n"
                "Recommended action: (a recommendation for the human — you are not authorized to decide anything yourself)"
            )
            resp = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        except Exception as err:
            logger.warning("LLM investigation failed, using template: %s", err)
            return (
                f"[templated, LLM call failed] {cluster['event_count']} suspected card-testing "
                f"events. Threshold tightened {old_threshold:.3f} -> {new_threshold:.3f}."
            )

    def execute_autonomous_policy_recalibration(self):
        cluster = self._summarize_cluster()
        evidence = self._gather_evidence(cluster)
        old_threshold = self.model_engine.optimal_threshold
        new_threshold = self.model_engine.adjust_threshold(
            0.8, reason="card_testing_burst_detected"
        )
        note = self._generate_incident_note(evidence, old_threshold, new_threshold)

        logger.info("AgenticGuardrail recalibration: %s", note)
        self.incident_log.append(
            {
                "cluster_summary": cluster,
                "device_history": evidence["device_history"],
                "old_threshold": old_threshold,
                "new_threshold": new_threshold,
                "note": note,
            }
        )
        self.anomaly_buffer.clear()