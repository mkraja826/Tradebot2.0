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



def _compact_market_context(market: dict) -> dict:
    """Keep execution-relevant evidence, not duplicate full exchange payloads.

    The planner already receives the approved product catalog separately.
    Large duplicate option records increase inference costs and can crowd out
    the required final JSON. Do not discard bid/ask, greeks, IV, expiries,
    liquidity and fees: strategies need those to assess execution risk.
    """
    if not isinstance(market, dict) or not isinstance(market.get("core"), dict):
        return market
    core = market["core"]
    ticker = core.get("ticker") or {}
    technical = market.get("technical") or {}

    def compact_quote(quote):
        return {name: quote[name] for name in (
            "product_id", "bid", "ask", "bid_iv", "ask_iv", "mark_price",
            "greeks", "volume", "open_interest", "taker_commission_rate",
            "age_seconds",
        ) if name in quote}

    return {
        "environment": market.get("environment"),
        "session_phase": market.get("session_phase"),
        "trading_schedule": market.get("trading_schedule", "nyse"),
        "max_hold_seconds": market.get("max_hold_seconds"),
        "collected_at": market.get("collected_at"),
        "btc": {
            "best_bid": core.get("best_bid"),
            "best_ask": core.get("best_ask"),
            "book_age_seconds": core.get("book_age_seconds"),
            "spot_price": ticker.get("spot_price"),
            "mark_price": ticker.get("mark_price"),
            "ticker_age_seconds": ticker.get("age_seconds"),
        },
        "technical": {
            "return_1h_pct": technical.get("return_1h_pct"),
            "realized_vol_1h_pct": technical.get("realized_vol_1h_pct"),
            "latest": technical.get("latest"),
            "recent_candles": technical.get("last_24", [])[-8:],
        },
        "futures": [compact_quote(q) for q in market.get("futures", [])],
        "options": [compact_quote(q) for q in market.get("options", [])],
        "demo_funds": market.get("demo_funds"),
        "btc_positions": market.get("btc_positions"),
        "open_orders_count": market.get("open_orders_count"),
        "coverage": market.get("coverage"),
    }


class TopBillingClient:
    def __init__(self, *, api_key=None, transport=None):
        self.api_key = api_key if api_key is not None else os.getenv("TB_API_KEY", "")
        self._transport = transport or urlopen
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

class AIPlanner(TopBillingClient):
    """One Top Billing model, no unrequested extra models or fallback calls.

    Top Billing's selected DeepSeek route does not advertise structured-output
    support. Do not send response_format=json_object/json_schema. Request
    textual JSON and validate strictly. Malformed output is a failed decision,
    never a reason to submit an unvalidated order.
    """

    def __init__(self, *, api_key: str | None = None, model: str | None = None,
                 transport=None):
        super().__init__(api_key=api_key, transport=transport)
        self.model = model if model is not None else os.getenv("TB_MODEL", PRIMARY_MODEL)
        if self.model not in ALLOWED_MODELS:
            raise PlanError("AI model not in the approved low-cost model list")
        self.last_usage = None
        self.last_finish_reason = None

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
        schedule = market.get("trading_schedule", "nyse")
        if schedule not in ("nyse", "crypto-24x7"):
            raise PlanError("Unknown trading schedule in AI market context")
        timing_instruction = (
            "BTC crypto market is available around the clock; do not use NYSE hours "
            "as an entry filter. Pilot exit is enforced after at most "
            + str(market.get("max_hold_seconds") or 900)
            + " seconds, even if you would hold longer. "
            if schedule == "crypto-24x7"
            else "All positions must be closed before the end of the US stock session. "
        )
        instructions = (
            "You are researching Bitcoin derivatives on Delta India DEMO. "
            "Choose autonomously among futures, options, valid multi-leg strategies, "
            "hedges, or waiting; do not invent contract IDs. "
            + timing_instruction
            + "Use historical trades as evidence, not proof of an edge. "
            "Only choose products in the candidate list. "
            "Be aware of spreads, time decay, execution costs, uncertain margin "
            "and the possibility that no trade is best. "
            "Keep strategy under 80 characters and rationale under 250 characters "
            "to ensure the full JSON completes within the response budget. "
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
                    "market": _compact_market_context(market),
                    "products": simple_products,
                    "recent_trades": (recent_journal or [])[-6:],
                }, separators=(",", ":"), default=str)},
            ],
            # This is a real credit-spending call; cap generated tokens.
            "max_completion_tokens": 2048,
            # Deliberately omit response_format. The selected model does not
            # advertise structured-output capability in Top Billing's catalogue.
        }
        self.last_finish_reason = None
        self.last_usage = None
        response = self._call(TOPBILLING_CHAT_URL, body=payload, timeout=45)
        self.last_usage = response.get("usage")
        try:
            choice = response["choices"][0]
            if not isinstance(choice, dict):
                raise ValueError("Malformed AI choice")
            finish = choice.get("finish_reason")
            self.last_finish_reason = finish if isinstance(finish, str) else None
            if finish not in (None, "stop"):
                # Do not parse truncated content even if it appears to contain
                # plausible orders. No paid retry is made automatically.
                if finish == "length":
                    raise PlanError("AI response hit its completion-token limit; no plan accepted")
                raise PlanError("AI response stopped without completion; no plan accepted")
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content:
                raise ValueError("Empty model response")
            raw = json.loads(content)
        except PlanError:
            raise
        except (KeyError, TypeError, ValueError, IndexError):
            raise PlanError("AI did not return one complete JSON trading plan") from None
        return validate_plan(raw, allowed_products)
