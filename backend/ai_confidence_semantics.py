"""Explicit semantics for MediKiosk AI confidence-like signals.

These values are engineering/model signals, not measures of clinical truth.
Keeping the semantics centralized prevents a UI or downstream module from
accidentally presenting an AI score as diagnostic certainty.
"""
from __future__ import annotations

from typing import Any, Dict

SEMANTICS_VERSION = "1.0"

SEMANTICS: Dict[str, Dict[str, Any]] = {
    "classifier_score": {
        "label": "Classifier score",
        "unit": "0_to_1",
        "meaning": "Uncalibrated model score for the selected text class relative to competing classes.",
        "not_meaning": ["clinical probability", "diagnostic certainty", "model accuracy"],
        "action": "Use as a review signal only; confirm the underlying text and pathway with clinical staff.",
    },
    "extraction_evidence_score": {
        "label": "Extraction evidence score",
        "unit": "0_to_1",
        "meaning": "Heuristic strength of explicit textual evidence supporting an extracted field.",
        "not_meaning": ["clinical probability", "diagnostic certainty", "measurement accuracy"],
        "action": "Compare the extracted value with the original source before clinical use.",
    },
    "document_classification_score": {
        "label": "Document classification score",
        "unit": "0_to_1",
        "meaning": "Heuristic ranking score based on document-class evidence and separation from alternatives.",
        "not_meaning": ["clinical probability", "diagnostic certainty", "classifier accuracy"],
        "action": "Use the review threshold to decide whether document type needs human confirmation.",
    },
    "rule_match": {
        "label": "Rule match",
        "unit": "boolean",
        "meaning": "A deterministic rule matched available input evidence.",
        "not_meaning": ["probability", "diagnosis", "clinical certainty"],
        "action": "Review the matched evidence and follow the clinical workflow; a non-match does not prove safety.",
    },
    "verification_status": {
        "label": "Human verification status",
        "unit": "categorical",
        "meaning": "Whether a human reviewer explicitly confirmed an extracted value.",
        "not_meaning": ["AI confidence", "model probability"],
        "action": "Human verification changes the workflow status; it does not turn an AI score into a probability of truth.",
    },
    "ux_confidence": {
        "label": "Interaction confidence",
        "unit": "categorical",
        "meaning": "A workflow/interaction state such as high, medium, or low used to choose fallback behavior.",
        "not_meaning": ["clinical probability", "model probability", "diagnostic certainty"],
        "action": "Use only for interaction handling and fallback decisions.",
    },
}


def confidence_semantics(kind: str) -> Dict[str, Any]:
    """Return a defensive copy of the semantic contract for a confidence-like signal."""
    if kind not in SEMANTICS:
        raise KeyError(f"Unknown confidence semantics: {kind}")
    return {"version": SEMANTICS_VERSION, "kind": kind, **SEMANTICS[kind]}
