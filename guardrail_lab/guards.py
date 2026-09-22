"""Guards run in Python, outside the model. Pattern checks are teaching heuristics."""
import ast
import math
import operator
import re
import unicodedata


class GuardError(Exception):
    def __init__(self, category: str, code: str, message: str):
        super().__init__(message)
        self.category, self.code, self.message = category, code, message


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return "".join(c for c in text if unicodedata.category(c) != "Cf")


PATTERNS = [
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{8,}", re.I), "Bearer [REDACTED_KEY]"),
    (re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I), "[REDACTED_EMAIL]"),
    (re.compile(r"\b[A-Z]{1,2}\d{6}\([0-9A]\)", re.I), "[REDACTED_HKID]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[REDACTED_LONG_NUMBER]"),
    (re.compile(r"(?<!\w)(?:\+?852[ -]?)?[2-9]\d{3}[ -]?\d{4}(?!\w)"), "[REDACTED_PHONE]"),
]
INJECTION = re.compile(
    r"(?:ignore|bypass|override|disable).{0,45}(?:previous|system|instructions|guardrails|rules|approval)"
    r"|(?:reveal|show|print|dump|expose).{0,35}(?:system prompt|api.?key|environment variables|\.env)"
    r"|\byou are now (?:root|admin|administrator)\b"
    r"|忽略.{0,12}(?:指令|規則)|繞過.{0,12}(?:審批|限制|規則)|顯示.{0,10}(?:密鑰|金鑰)", re.I | re.S)
UNSAFE_EXECUTION = re.compile(
    r"\b(?:os\.system|subprocess|__import__|exec\s*\(|eval\s*\(|rm\s+-rf)"
    r"|(?:run|execute).{0,20}(?:shell|powershell|terminal|command|python code)"
    r"|(?:read|open|download).{0,35}(?:\.env|/etc/|[A-Z]:\\|https?://)"
    r"|(?:delete|erase).{0,25}(?:files|folder|logs)", re.I | re.S)


def redact(text: str, api_key: str = "") -> tuple[str, bool]:
    original = text
    if api_key:
        text = text.replace(api_key, "[REDACTED_KEY]")
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text, text != original


def check_input(text: str, api_key: str = "") -> tuple[str, bool]:
    if not isinstance(text, str) or not text.strip():
        raise GuardError("Input", "empty_input", "Enter a question first.")
    if len(text) > 2000 or len(text.encode("utf-8")) > 8000:
        raise GuardError("Input", "input_too_long", "Limit each question to 2,000 characters and 8,000 UTF-8 bytes.")
    text = normalize(text).strip()
    if INJECTION.search(text):
        raise GuardError("Input", "injection_pattern", "A known instruction-override or secret-extraction pattern was blocked.")
    if UNSAFE_EXECUTION.search(text):
        raise GuardError("Execution", "unsafe_execution", "This lab cannot run code, browse arbitrary URLs, or read/delete your files.")
    return redact(text, api_key)


def filter_output(text: str, api_key: str = "") -> tuple[str, bool]:
    if not isinstance(text, str) or not text.strip():
        raise GuardError("Output", "empty_output", "The model returned no usable answer. Try a tool-capable text model.")
    text, masked = redact(normalize(text), api_key)
    if len(text) > 4000:
        text = text[:4000] + "\n[Display capped at 4,000 characters.]"
        masked = True
    return text, masked


def calculate(expression: str) -> str:
    """Only small numeric ASTs. Never eval(), exec(), names, calls, powers or attributes."""
    if not isinstance(expression, str) or not 1 <= len(expression) <= 120:
        raise GuardError("Execution", "invalid_expression", "Use a numeric expression of 1–120 characters.")
    try:
        tree = ast.parse(expression, mode="eval")
        if len(list(ast.walk(tree))) > 40:
            raise ValueError
        binary = {ast.Add: operator.add, ast.Sub: operator.sub,
                  ast.Mult: operator.mul, ast.Div: operator.truediv}
        unary = {ast.UAdd: operator.pos, ast.USub: operator.neg}
        def visit(node, depth=0):
            if depth > 12:
                raise ValueError
            if isinstance(node, ast.Expression):
                value = visit(node.body, depth + 1)
            elif isinstance(node, ast.Constant) and type(node.value) in (int, float):
                value = node.value
            elif isinstance(node, ast.BinOp) and type(node.op) in binary:
                value = binary[type(node.op)](visit(node.left, depth+1), visit(node.right, depth+1))
            elif isinstance(node, ast.UnaryOp) and type(node.op) in unary:
                value = unary[type(node.op)](visit(node.operand, depth+1))
            else:
                raise ValueError
            if not math.isfinite(value) or abs(value) > 1_000_000_000:
                raise ValueError
            return value
        return format(visit(tree), ".12g")
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, RecursionError, TypeError):
        raise GuardError("Execution", "unsafe_expression", "Only bounded numbers, parentheses, +, -, *, and / are allowed. No code, powers, or division by zero.") from None
