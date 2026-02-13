from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import requests

from app.config import Settings
from app.industry_taxonomy import CONTROLLED_INDUSTRY_LABELS, KEYWORD_RULES

logger = logging.getLogger(__name__)

_CANONICAL_LABELS = {label.lower(): label for label in CONTROLLED_INDUSTRY_LABELS}


@dataclass(slots=True)
class SymbolForLabeling:
    symbol_id: int
    ticker: str
    name: str | None


@dataclass(slots=True)
class IndustryPrediction:
    label: str | None
    confidence: float


def _clamp_confidence(confidence: float | int | None, default: float) -> float:
    if confidence is None:
        return default
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return default
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return value


def heuristic_prediction(ticker: str, name: str | None) -> IndustryPrediction:
    haystack = f"{ticker} {name or ''}".lower()
    for label, keywords in KEYWORD_RULES:
        if any(keyword in haystack for keyword in keywords):
            return IndustryPrediction(label=label, confidence=0.72)

    if not name:
        return IndustryPrediction(label=None, confidence=0.10)

    if " holdings" in haystack or " holding" in haystack:
        return IndustryPrediction(label="Other", confidence=0.30)

    return IndustryPrediction(label="Other", confidence=0.25)


class IndustryLabeler:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def label_batch(self, symbols: list[SymbolForLabeling]) -> dict[int, IndustryPrediction]:
        if not symbols:
            return {}

        results: dict[int, IndustryPrediction] = {}
        llm_results: dict[int, IndustryPrediction] = {}

        if self.settings.industry_llm_enabled and self.settings.openai_api_key:
            llm_results = self._label_batch_with_llm(symbols)

        for symbol in symbols:
            prediction = llm_results.get(symbol.symbol_id)
            if prediction is None:
                prediction = heuristic_prediction(symbol.ticker, symbol.name)
            results[symbol.symbol_id] = prediction

        return results

    def _label_batch_with_llm(self, symbols: list[SymbolForLabeling]) -> dict[int, IndustryPrediction]:
        prompt_rows = [
            {
                "symbol_id": item.symbol_id,
                "ticker": item.ticker,
                "name": item.name,
            }
            for item in symbols
        ]
        allowed_labels = ", ".join(CONTROLLED_INDUSTRY_LABELS)

        system_prompt = (
            "You label US-listed public companies into a controlled industry vocabulary. "
            "Return strict JSON only."
        )
        user_prompt = (
            "For each input company, infer one industry label from the allowed labels. "
            "If uncertain, choose 'Other'. If insufficient data, set label to null. "
            "Confidence must be between 0 and 1.\n"
            f"Allowed labels: [{allowed_labels}]\n"
            "Output schema: {'results':[{'symbol_id':int,'label':string|null,'confidence':float}]}\n"
            f"Input: {json.dumps(prompt_rows, ensure_ascii=True)}"
        )

        try:
            response = requests.post(
                f"{self.settings.openai_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.settings.openai_model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            parsed = _parse_json_object(content)
            if not isinstance(parsed, dict):
                return {}

            raw_results = parsed.get("results")
            if not isinstance(raw_results, list):
                return {}

            predictions: dict[int, IndustryPrediction] = {}
            for row in raw_results:
                if not isinstance(row, dict):
                    continue
                symbol_id = row.get("symbol_id")
                if not isinstance(symbol_id, int):
                    continue

                raw_label = row.get("label")
                label: str | None
                if raw_label is None:
                    label = None
                else:
                    candidate = str(raw_label).strip()
                    label = _CANONICAL_LABELS.get(candidate.lower())

                confidence = _clamp_confidence(row.get("confidence"), default=0.30)
                predictions[symbol_id] = IndustryPrediction(label=label, confidence=confidence)

            return predictions
        except Exception:
            logger.exception("LLM industry labeling failed for batch of %s symbols", len(symbols))
            return {}


def _parse_json_object(text: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
