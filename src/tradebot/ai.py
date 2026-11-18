"""Top Billing AI strategy planner for BTC demo trading.

A single low-cost model is intentionally allowed until our own out-of-sample
trading evaluation justifies a second. Keys stay in environment variables and
are never included in source files, journals or API request bodies.
"""
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from tradebot.delta import is_btc_contract

TOPBILLING_CHAT_URL = "https://api.topbilling.in/v1/chat/completions"
TOPBILLING_MODELS_URL = "https://api.topbilling.in/v1/models"
PRIMARY_MODEL = "tb-deepseek-v4-1-flash"
ALLOWED_MODELS = frozenset({PRIMARY_MODEL})


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
    """Permit arbitrary strategy names, but reject invalid executable legs."""
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
        raise PlanError("Expected 0-12 legs")
    valid = []
    for leg in legs:
        if not isinstance(leg, dict):
            raise PlanError("Malformed leg")
        product_id = leg.get("product_id")
        size = leg.get("size")
        side = leg.get("side")
        if (type(product_id) is not int or product_id not in allowed
                or type(size) is not int or size < 1
                or side not in ("buy", "sell")):
            raise PlanError("Leg references invalid BTC contract, side or size")
        valid.append(OrderIntent(product_id, side, size))
    return TradePlan(strategy.strip(), rationale.strip(), tuple(valid))


class AIPlanner:
    """One Top Billing model, no unrequested extra models or fallback calls.

    Top Billing's selected DeepSeek route does not advertise structured-output
    support. Do not send response_format=json_object/json_schema. Request
    textual JSON and validate strictly. Malformed output is a failed decision,
    never a reason to submit an unvalidated order.
    """

    def __init__(self, *, api_key: str | None = None, model: str | None = None,
                 transport=None):
        self.api_key = api_key if api_key is not None else os.getenv("TB_API_KEY", "")
        self.model = model if model is not None else os.getenv("TB_MODEL", PRIMARY_MODEL)
        if self.model not in ALLOWED_MODELS:
            raise PlanError("AI model not in the approved low-cost model list")
        self._transport = transport or urlopen
        self.last_usage = None
        self.last_request_id = None

    def _call(self, url: str, *, body: dict | None = None, timeout: int = 45) -> dict:
        if not self.api_key:
            raise PlanError("TB_API_KEY is required; store it in a local secret environment")
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "tradebot2-topbilling/0.1",
        }
        req = Request(url, headers=headers, method="POST" if body is not None else "GET",
                      data=json.dumps(body, separators=(",", ":")).encode()
                      if body is not None else None)
        try:
            with self._transport(req, timeout=timeout) as response:
                result = json.load(response)
                self.last_request_id = response.headers.get("x-request-id")
        except HTTPError as exc:
            # HTTP errors may contain sensitive upstream bodies. Do not log
            # response body, request headers or full auth-bearing object.
            raise PlanError(f"Top Billing API HTTP {exc.code}") from None
        except (URLError, OSError, TimeoutError) as exc:
            raise PlanError("Top Billing API network error") from None
        except (ValueError, TypeError):
            raise PlanError("Invalid Top Billing API JSON response") from None
        if not isinstance(result, dict):
            raise PlanError("Malformed Top Billing response")
        return result

    def check_model_access(self) -> bool:
        """Read-only model catalogue check, no paid completion request."""
        data = self._call(TOPBILLING_MODELS_URL, timeout=15)
        models = data.get("data")
        if not isinstance(models, list):
            raise PlanError("Malformed Top Billing model catalogue")
        return any(isinstance(entry, dict) and entry.get("id") == self.model
                   for entry in models)

    def propose(self, market: dict, products: list[dict],
                recent_journal: list[dict] | None = None) -> TradePlan:
        allowed_products = [p for p in products if is_btc_contract(p)]
        if not allowed_products:
            raise PlanError("No live BTC contracts available")
        simple_products = [
            {"id": p["id"], "symbol": p["symbol"],
             "contract_type": p["contract_type"],
             "strike_price": p.get("strike_price"),
             "settlement_time": p.get("settlement_time"),
             "tick_size": p.get("tick_size"),
             "contract_value": p.get("contract_value")}
            for p in allowed_products
        ]
        instructions = (
            "You are researching Bitcoin derivatives on Delta India DEMO. "
            "Choose autonomously among futures, options, valid multi-leg strategies, "
            "hedges, or waiting; do not invent contract IDs. "
            "All positions must be closed before the end of the US stock session. "
            "Use historical trades as evidence, not proof of an edge. "
            "Only choose products in the candidate list. "
            "Be aware of spreads, time decay, execution costs, uncertain margin "
            "and the possibility that no trade is best. "
            "Return exactly one syntactically valid JSON object, with keys "
            "strategy (string), rationale (string), and orders (array of 0-12 "
            "objects each containing product_id (integer), side ('buy' or 'sell'), "
            "size (positive integer)). No markdown, code fences or extra prose. "
            "An empty orders array means WAIT. Never include API credentials."
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": json.dumps({
                    "market": market, "products": simple_products,
                    "recent_trades": (recent_journal or [])[-12:],
                }, separators=(",", ":"), default=str)},
            ],
            # This is a real credit-spending call; cap generated tokens.
            "max_completion_tokens": 2048,
            # Deliberately omit response_format. The selected model does not
            # advertise structured-output capability in Top Billing's catalogue.
        }
        response = self._call(TOPBILLING_CHAT_URL, body=payload, timeout=45)
        self.last_usage = response.get("usage")
        try:
            choice = response["choices"][0]
            if choice.get("finish_reason") not in (None, "stop"):
                raise ValueError("Incomplete model response")
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content:
                raise ValueError("Empty model response")
            raw = json.loads(content)
        except (KeyError, TypeError, ValueError, IndexError):
            raise PlanError("AI did not return one complete JSON trading plan") from None
        return validate_plan(raw, allowed_products)
