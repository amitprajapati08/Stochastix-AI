"""
Asymmetric-cost LightGBM classifier for the Sentinel risk engine.

Business rule (stated in the problem brief): declining a legitimate
transaction costs roughly 8x more than letting one low-value fraud-test
transaction through. That means, in cost terms:
    cost(false positive)  >>  cost(false negative)
This file enforces that ratio in TWO places, deliberately:
  1. Training-time sample weights bias the model away from flagging
     legitimate traffic as fraud in the first place.
  2. Decision-time threshold search picks the operating point that
     minimises the SAME cost ratio on held-out validation data.
If these two numbers ever disagree, the model and the deployed decision
policy are optimizing for different things — which is exactly the bug
in the original spec (it had fp_cost=150 < fn_cost=800, backwards from
the stated 8x rule). Keep them consistent.

Decision logic itself (ALLOW/STEP-UP/BLOCK) lives in app/policy.py, not
here — this file's only job is producing a risk PROBABILITY. Keeping
"what is the risk" separate from "what do we do about it" is the whole
AI-judgment story for this project.
"""

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from typing import List, Dict, Any, Tuple
from app import policy

FEATURE_COLUMNS = [
    "amount",
    "velocity_60s_card",
    "velocity_60s_ip",
    "velocity_60s_device",
    "merchant_diversity_device",
]

# Single source of truth for the asymmetric cost ratio, used both to weight
# training samples and to pick the deployed decision threshold.
FALSE_POSITIVE_COST = 800   # cost of wrongly declining a legitimate transaction
FALSE_NEGATIVE_COST = 100   # cost of letting one low-value fraud-test txn through
# Ratio here is 8x, matching the stated business rule.


class AsymmetricalSentinelModel:
    def __init__(self):
        self.model = None
        self.optimal_threshold = 0.5
        self.threshold_floor = 0.03   # safety rail so the adaptive loop can't zero itself out
        self.threshold_ceiling = 0.9

    def train_on_simulation_pool(self, training_pool: List[Dict[str, Any]]):
        df = pd.DataFrame(training_pool)
        X = df[FEATURE_COLUMNS]
        y = df["is_fraud"]

        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=0.3, random_state=42, stratify=y
        )

        # Weight legitimate samples up so misclassifying a real customer as
        # fraud costs the model more during training than missing a fraud
        # test transaction. Ratio matches FALSE_POSITIVE_COST / FALSE_NEGATIVE_COST.
        weight_ratio = FALSE_POSITIVE_COST / FALSE_NEGATIVE_COST
        weights = np.where(y_train == 0, weight_ratio, 1.0)

        train_dataset = lgb.Dataset(X_train, label=y_train, weight=weights)
        val_dataset = lgb.Dataset(X_val, label=y_val, reference=train_dataset)

        params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "boosting_type": "gbdt",
            "learning_rate": 0.08,
            "num_leaves": 15,
            "max_depth": 4,
            "verbosity": -1,
            "num_threads": 2,
        }
        self.model = lgb.train(
            params, train_dataset, num_boost_round=60, valid_sets=[val_dataset]
        )
        metrics = self.calculate_optimal_boundary(X_val, y_val)
        return metrics

    def calculate_optimal_boundary(self, X_val: pd.DataFrame, y_val: pd.Series) -> Dict[str, Any]:
        raw_predictions = self.model.predict(X_val)
        y_val_arr = y_val.to_numpy()
        best_cost = float("inf")
        best_threshold = 0.5
        best_stats = {}

        for threshold_candidate in np.linspace(0.01, 0.95, 200):
            decisions = (raw_predictions >= threshold_candidate).astype(int)
            tp = int(np.sum((decisions == 1) & (y_val_arr == 1)))
            fp = int(np.sum((decisions == 1) & (y_val_arr == 0)))
            fn = int(np.sum((decisions == 0) & (y_val_arr == 1)))
            tn = int(np.sum((decisions == 0) & (y_val_arr == 0)))

            net_cost = (fp * FALSE_POSITIVE_COST) + (fn * FALSE_NEGATIVE_COST)

            if net_cost < best_cost:
                best_cost = net_cost
                best_threshold = float(threshold_candidate)
                precision = tp / (tp + fp) if (tp + fp) else 0.0
                recall = tp / (tp + fn) if (tp + fn) else 0.0
                best_stats = {
                    "threshold": best_threshold,
                    "precision": precision,
                    "recall": recall,
                    "false_positives": fp,
                    "false_negatives": fn,
                    "true_positives": tp,
                    "true_negatives": tn,
                    "net_cost_inr_units": net_cost,
                }

        self.optimal_threshold = best_threshold
        return best_stats

    def score_transaction(self, feature_vector: Dict[str, Any]) -> Tuple[float, str]:
        input_matrix = pd.DataFrame([[feature_vector[c] for c in FEATURE_COLUMNS]], columns=FEATURE_COLUMNS)
        prob = float(self.model.predict(input_matrix)[0])
        decision = policy.decide(prob, self.optimal_threshold)
        return prob, decision

    def adjust_threshold(self, multiplier: float, reason: str = "") -> float:
        """Bounded threshold adjustment used by the adaptive control loop.
        Never allowed outside [threshold_floor, threshold_ceiling] so an
        automated recalibration can't accidentally block (or admit) all
        traffic."""
        proposed = self.optimal_threshold * multiplier
        self.optimal_threshold = float(
            min(max(proposed, self.threshold_floor), self.threshold_ceiling)
        )
        return self.optimal_threshold