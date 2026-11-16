"""Autonomous, model-driven strategy planning. Execution is a separate concern."""
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

from tradebot.delta import is_btc_contract


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class OrderIntent:
    product_id: int
    side: str
    size: int


@dataclass(frozen=True)
class TradePlan:
    strategy: str
    rationale: str
    orders: tuple[OrderIntent, ...]


def validate_plan(raw: dict[str, Any], products: list[dict]) -> TradePlan:
    """Accept arbitrary strategy names but only valid BTC live contract orders."""
    if not isinstance(raw, dict):
        raise PlanError("Model output must be a JSON object")
    allowed = {p["id"] for p in products if is_btc_contract(p)}
    strategy, rationale = raw.get("strategy"), raw.get("rationale")
    if not isinstance(strategy, str) or not strategy.strip():
        raise PlanError("Strategy explanation required")
    if not isinstance(rationale, str) or not rationale.strip():
        raise PlanError("Model rationale required")
    legs = raw.get("orders")
    if not isinstance(legs, list) or len(legs) > 12:
        raise PlanError("Expected 0–12 legs")
    valid = []
    for leg in legs:
        if not isinstance(leg, dict):
            raise PlanError("Malformed leg")
        product_id = leg.get("product_id")
        size = leg.get("size")
        side = leg.get("side")
        if (type(product_id) is not int or product_id not in allowed
                or type(size) is not int or size < 1 or side not in ("buy", "sell")):
            raise PlanError("Leg references invalid BTC contract, side, or size")
        valid.append(OrderIntent(product_id, side, size))
    return TradePlan(strategy.strip(), rationale.strip(), tuple(valid))


class AIPlanner:
    """Planner uses an OpenAI API key kept outside source control.

    The model is free to choose no trade, a single instrument, or a multi-leg
    combination. This version is deliberation only; it does not execute orders.
    """

    def __init__(self, *, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY", "")
        self.model = model if model is not None else os.getenv("OPENAI_MODEL", "")

    def propose(self, market: dict, products: list[dict],
                recent_journal: list[dict] | None = None) -> TradePlan:
        if not self.api_key or not self.model:
            raise PlanError("OPENAI_API_KEY and OPENAI_MODEL must be set for AI planning")
        allowed_products = [p for p in products if is_btc_contract(p)]
        if not allowed_products:
            raise PlanError("No live BTC contracts to consider")
        simple_products = [
            {"id": p["id"], "symbol": p["symbol"],
             "contract_type": p["contract_type"],
             "strike_price": p.get("strike_price"),
             "settlement_time": p.get("settlement_time"),
             "tick_size": p.get("tick_size")}
            for p in allowed_products
        ]
        instructions = (
            "You are researching Bitcoin derivatives on Delta India DEMO. "
            "Choose a strategy autonomously from the observed market, including no trade. "
            "You may choose futures, options, or any valid multi-leg combination. "
            "Do not invent a product ID. Choose only IDs from the provided list. "
            "No overnight positions: trading is permitted only in the specified session. "
            "Use the trade history to reassess hypotheses, not to assume past success "
            "guarantees future profit. Return only JSON object with strategy, rationale, "
            "and orders array of {product_id: int, side: buy|sell, size: positive int}. "
            "An empty orders array means WAIT. Do not include credentials."
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": json.dumps({
                    "market": market, "products": simple_products,
                    "recent_trades": (recent_journal or [])[-20:],
                }, separators=(",", ":"))},
            ],
            "response_format": {"type": "json_object"},
        }
        req = Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json",
                     "User-Agent": "tradebot2-research/0.1"},
            method="POST")
        with urlopen(req, timeout=45) as response:
            reply = json.load(response)
        try:
            raw = json.loads(reply["choices"][0]["message"]["content"])
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise PlanError("Model did not return parseable structured JSON") from exc
        return validate_plan(raw, allowed_products)
