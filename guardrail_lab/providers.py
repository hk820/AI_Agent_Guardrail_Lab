"""NexLLM transport and a clearly labelled deterministic classroom simulator."""
import http.client
import json
import re
import socket
import ssl
import time
import uuid
from .guards import GuardError


def strict_json(text):
    def invalid_constant(_):
        raise ValueError("Non-finite JSON numbers are forbidden.")
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field.")
            result[key] = value
        return result
    return json.loads(text, parse_constant=invalid_constant, object_pairs_hook=unique_pairs)


def completion_body(config, messages, schemas, model):
    return {"model": model, "messages": messages, "tools": schemas,
            "tool_choice": "auto", "stream": False,
            config.token_parameter: config.max_output_tokens}


class NexLLMProvider:
    def __init__(self, config):
        self.config = config

    def request(self, method, route, payload=None, deadline=None):
        if not self.config.api_key:
            raise GuardError("Fail-safe", "missing_key", "Enter NEXLLM_API_KEY in .env and restart the server before using NexLLM mode.")
        if route not in {"/models", "/chat/completions"}:
            raise GuardError("Permission", "route_denied", "This API route is not allowed.")
        deadline = deadline or time.monotonic() + self.config.request_timeout
        def remaining():
            seconds = min(self.config.request_timeout, deadline - time.monotonic())
            if seconds <= 0:
                raise GuardError("Budget", "time_limit", "The turn deadline was reached. No automatic retry was made.")
            return seconds
        body = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if body is not None and len(body) > self.config.max_request_bytes:
            raise GuardError("Budget", "request_size", "The model request exceeds the byte limit. Clear conversation memory or shorten your question.")
        # The fixed host and routes prohibit prompt-directed egress. HTTPS verifies certificates.
        conn = http.client.HTTPSConnection("www.nexllm.ai", 443, timeout=remaining(), context=ssl.create_default_context())
        try:
            conn.connect()
            sock = conn.sock
            sock.settimeout(remaining())
            conn.request(method, "/v1" + route, body=body, headers={
                "Authorization": "Bearer " + self.config.api_key,
                "Content-Type": "application/json", "Accept": "application/json",
                "Accept-Encoding": "identity", "User-Agent": "GuardrailLab/1.0"})
            sock.settimeout(remaining())
            response = conn.getresponse()
            if response.status != 200:
                explanations = {
                    400: "The provider rejected the request. Check the model ID, function-calling support, and NEXLLM_TOKEN_PARAMETER.",
                    401: "NexLLM authentication failed. Check NEXLLM_API_KEY in .env.",
                    403: "NexLLM denied access. Check your account and model permissions.",
                    404: "The endpoint or model was not found. Check the model ID in your NexLLM account.",
                    429: "NexLLM rate or quota limit reached. Check your account before trying again.",
                }
                message = explanations.get(response.status, "NexLLM returned an unsuccessful HTTP response. Check provider availability and account configuration.")
                # No redirects, raw error-body display, or automatic retries.
                raise GuardError("Fail-safe", "provider_http_error", message + " No automatic retry was made.")
            chunks, size = [], 0
            while True:
                sock.settimeout(remaining())
                chunk = response.read1(8192)
                if not chunk:
                    break
                size += len(chunk)
                if size > 262144:
                    raise GuardError("Output", "response_too_large", "The provider response exceeded 256 KiB and was rejected.")
                chunks.append(chunk)
                if response.isclosed():
                    break  # Content-Length reached; a Connection: close socket may already be closed.
            result = strict_json(b"".join(chunks).decode("utf-8"))
            if not isinstance(result, dict):
                raise ValueError
            return result
        except GuardError:
            raise
        except (socket.timeout, TimeoutError):
            raise GuardError("Fail-safe", "provider_timeout", "NexLLM timed out. No automatic retry was made; the provider may still bill a submitted request.") from None
        except (OSError, http.client.HTTPException):
            raise GuardError("Fail-safe", "provider_connection", "Could not securely connect to NexLLM. Check internet access, certificates, and provider availability.") from None
        except (ValueError, UnicodeError, RecursionError):
            raise GuardError("Output", "invalid_provider_json", "The provider returned invalid JSON. The agent stopped.") from None
        finally:
            conn.close()

    def complete(self, messages, schemas, model, deadline):
        result = self.request("POST", "/chat/completions",
                              completion_body(self.config, messages, schemas, model), deadline)
        try:
            choice = result["choices"][0]
            return {"message": choice["message"], "finish_reason": choice.get("finish_reason"),
                    "usage": result.get("usage")}
        except (KeyError, IndexError, TypeError):
            raise GuardError("Output", "invalid_provider_shape", "NexLLM returned an unexpected completion structure.") from None

    def models(self):
        data = self.request("GET", "/models").get("data")
        if not isinstance(data, list):
            raise GuardError("Output", "invalid_models", "The provider's model list was not in the expected format. Enter a model ID manually.")
        return sorted({x["id"] for x in data if isinstance(x, dict) and isinstance(x.get("id"), str)
                       and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", x["id"])})[:300]


class DemoProvider:
    """Not an LLM. Its scripted decisions pass through the same Python harness."""
    @staticmethod
    def answer(text):
        return {"message": {"role": "assistant", "content": text}, "usage": None, "finish_reason": "stop"}

    @staticmethod
    def call(name, args):
        return {"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_" + uuid.uuid4().hex[:12], "type": "function",
             "function": {"name": name, "arguments": json.dumps(args)}}]}, "usage": None, "finish_reason": "tool_calls"}

    def complete(self, messages, schemas, model, deadline):
        last = max(i for i, item in enumerate(messages) if item["role"] == "user")
        prompt = messages[last]["content"]
        lower = prompt.lower()
        results = [m for m in messages[last+1:] if m["role"] == "tool"]
        if "[demo:unknown_tool]" in lower:
            return self.call("send_payment", {"amount": 50})
        if "[demo:unsafe_calculator]" in lower:
            return self.call("calculate", {"expression": "__import__('os').getcwd()"})
        if "[demo:loop]" in lower:
            return self.call("search_policy", {"query": "tools"})
        if "[demo:output_secret]" in lower:
            return self.answer("Synthetic output: learner@example.test; sk-CLASSROOMSECRET123456. These should be masked.")
        if "[demo:provider_failure]" in lower:
            raise GuardError("Fail-safe", "demo_provider_failure", "Simulated provider failure. The run stopped without a retry.")
        if "[demo:bad_json]" in lower:
            result = self.call("get_order", {})
            result["message"]["tool_calls"][0]["function"]["arguments"] = "{broken json"
            return result
        if ("refund" in lower or "退款" in lower) and not any(word in lower for word in ("policy", "policies", "政策", "規則")):
            order = re.search(r"ORD-\d{4}", prompt, re.I)
            amount = re.search(r"(?:hkd|\$)\s*(\d+(?:\.\d+)?)", prompt, re.I)
            if not order or not amount:
                return self.answer("Try: Refund HKD 80 for ORD-1001 because the item is damaged. This is a simulation and requires an approval click.")
            if not results:
                return self.call("get_order", {"order_id": order.group().upper()})
            return self.call("propose_refund", {"order_id": order.group().upper(),
                             "amount_hkd": float(amount.group(1)), "reason": "Classroom refund exercise"})
        if results:
            data = strict_json(results[-1]["content"])
            if "result" in data:
                return self.answer("Calculation result: " + str(data["result"]))
            if "policies" in data:
                return self.answer("\n\n".join(p["id"] + ": " + p["text"] for p in data["policies"]))
            return self.answer("Synthetic order result:\n" + json.dumps(data, indent=2, ensure_ascii=False))
        if lower.startswith(("calculate", "計算")):
            expression = re.sub(r"^(?:calculate|計算)\s*:?\s*", "", prompt, flags=re.I)
            return self.call("calculate", {"expression": expression})
        order = re.search(r"ORD-\d{4}", prompt, re.I)
        if order:
            return self.call("get_order", {"order_id": order.group().upper()})
        if "what did i" in lower or "previous question" in lower:
            previous = [m["content"] for m in messages[:last] if m["role"] == "user"]
            return self.answer("Previous sanitized question: " + previous[-1] if previous else "No earlier question is available. Conversation memory is off or empty.")
        if any(x in lower for x in ("policy", "guardrail", "privacy", "budget", "tools", "規則")):
            return self.call("search_policy", {"query": prompt[:120]})
        return self.answer("Offline simulator: try a scenario on the left, ask for the refund policy, calculate (120 + 80) / 2, or look up ORD-1001. For open-ended AI conversations, select NexLLM mode.")
