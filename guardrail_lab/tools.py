"""Fixed, typed tool registry. A tool can propose a refund, but cannot execute one."""
from decimal import Decimal, InvalidOperation
import json
import re
from .config import ROOT
from .guards import GuardError, calculate, redact


def schema(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": required, "additionalProperties": False}}}


SCHEMAS = [
    schema("search_policy", "Read local synthetic classroom policies. Cite returned policy IDs.",
           {"query": {"type": "string", "maxLength": 120}}, ["query"]),
    schema("calculate", "Calculate small numeric expressions with + - * / and parentheses only.",
           {"expression": {"type": "string", "maxLength": 120}}, ["expression"]),
    schema("get_order", "Look up an allowlisted synthetic order ORD-1001, ORD-1002, or ORD-1003.",
           {"order_id": {"type": "string"}}, ["order_id"]),
    schema("propose_refund", "Propose a simulated HKD refund. This never executes a refund; human approval is required.",
           {"order_id": {"type": "string"}, "amount_hkd": {"type": "number"},
            "reason": {"type": "string", "maxLength": 200}}, ["order_id", "amount_hkd", "reason"]),
]


class ToolBox:
    def __init__(self):
        self.orders = {x["order_id"]: x for x in json.loads((ROOT / "data/orders.json").read_text())}
        self.policies = json.loads((ROOT / "data/policies.json").read_text())

    def validate(self, name, args):
        spec = next((s["function"]["parameters"] for s in SCHEMAS if s["function"]["name"] == name), None)
        if spec is None:
            raise GuardError("Tool", "tool_not_allowed", "The model requested a tool outside the allowlist. Nothing was executed.")
        if not isinstance(args, dict) or set(args) != set(spec["required"]):
            raise GuardError("Tool", "invalid_arguments", "Tool arguments have missing or unexpected fields.")
        for key, rule in spec["properties"].items():
            value = args[key]
            if rule["type"] == "string" and (not isinstance(value, str) or not value.strip() or len(value) > rule.get("maxLength", 50)):
                raise GuardError("Tool", "invalid_arguments", "A tool string is empty, invalid, or too long.")
            if rule["type"] == "number" and type(value) not in (int, float):
                raise GuardError("Tool", "invalid_arguments", "Refund amount must be a JSON number, not text or a boolean.")
        if "order_id" in args and (not re.fullmatch(r"ORD-\d{4}", args["order_id"]) or args["order_id"] not in self.orders):
            raise GuardError("Permission", "order_not_allowed", "Only ORD-1001, ORD-1002, and ORD-1003 are accessible in this sandbox.")

    def refund_proposal(self, args, session, role, api_key):
        self.validate("propose_refund", args)
        if role != "operator":
            raise GuardError("Permission", "role_denied", "Viewer role cannot propose or approve refunds. Change LAB_ROLE in .env and restart for the operator exercise.")
        try:
            amount = Decimal(str(args["amount_hkd"]))
            if not amount.is_finite() or amount <= 0 or amount > 300 or amount != amount.quantize(Decimal("0.01")):
                raise ValueError
        except (InvalidOperation, ValueError):
            raise GuardError("Permission", "refund_limit", "A refund must be positive, use at most two decimal places, and not exceed HKD 300.") from None
        cents = int(amount * 100)
        order = self.orders[args["order_id"]]
        paid = int(Decimal(str(order["paid_hkd"])) * 100)
        if not order["refundable"] or cents > paid - session.refunded.get(order["order_id"], 0):
            raise GuardError("Permission", "refund_ineligible", "The order is ineligible or the amount exceeds its remaining refundable balance.")
        reason, _ = redact(args["reason"], api_key)
        reason = reason[:200]
        return {"order_id": args["order_id"], "amount_hkd": float(amount), "reason": reason}

    def read(self, name, args, session):
        self.validate(name, args)
        if name == "calculate":
            return {"result": calculate(args["expression"])}
        if name == "get_order":
            order = dict(self.orders[args["order_id"]])
            order["refunded_hkd_in_this_sandbox"] = session.refunded.get(args["order_id"], 0) / 100
            return order
        if name == "search_policy":
            words = set(re.findall(r"[a-z]+", args["query"].lower()))
            matches = [p for p in self.policies if p["topic"] in words or p["id"].lower() in args["query"].lower()]
            return {"policies": matches or self.policies}
        raise GuardError("Tool", "invalid_dispatch", "This tool requires the approval path.")
