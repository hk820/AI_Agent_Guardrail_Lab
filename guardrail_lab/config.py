"""Small .env reader. No extra packages or API credentials are required for demo mode."""
from dataclasses import dataclass, field
from pathlib import Path
import os


ROOT = Path(__file__).resolve().parent.parent


def read_env(path: Path) -> dict[str, str]:
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError("Each non-comment .env line must use NAME=value.")
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
    return values


@dataclass(frozen=True)
class Config:
    api_key: str = field(default="", repr=False)
    base_url: str = "https://www.nexllm.ai/v1"
    model: str = ""
    token_parameter: str = "max_tokens"
    port: int = 8765
    role: str = "operator"
    max_llm_calls: int = 4
    max_tool_calls: int = 6
    max_live_calls: int = 40
    max_request_bytes: int = 48000
    max_output_tokens: int = 700
    request_timeout: int = 25
    turn_timeout: int = 75
    approval_ttl: int = 120
    audit_path: Path = ROOT / "logs" / "audit.jsonl"

    @classmethod
    def load(cls, path: Path = ROOT / ".env"):
        source = read_env(path)
        source.update({k: v for k, v in os.environ.items()
                       if k.startswith(("NEXLLM_", "LAB_"))})
        def get(k, default):
            return source.get(k, default).strip()
        def integer(k, default, low, high):
            try:
                value = int(get(k, str(default)))
            except ValueError:
                raise ValueError(f"{k} must be an integer.") from None
            if not low <= value <= high:
                raise ValueError(f"{k} must be between {low} and {high}.")
            return value
        base = get("NEXLLM_BASE_URL", cls.base_url).rstrip("/")
        # A prompt, tool argument, or UI field cannot change the API destination.
        if base != "https://www.nexllm.ai/v1":
            raise ValueError("NEXLLM_BASE_URL must be https://www.nexllm.ai/v1 in this lab.")
        role = get("LAB_ROLE", "operator")
        if role not in {"viewer", "operator"}:
            raise ValueError("LAB_ROLE must be viewer or operator.")
        token_parameter = get("NEXLLM_TOKEN_PARAMETER", "max_tokens")
        if token_parameter not in {"max_tokens", "max_completion_tokens"}:
            raise ValueError("NEXLLM_TOKEN_PARAMETER must be max_tokens or max_completion_tokens.")
        api_key = get("NEXLLM_API_KEY", "")
        if any(c.isspace() for c in api_key):
            raise ValueError("NEXLLM_API_KEY must not contain whitespace.")
        return cls(
            api_key=api_key, base_url=base, model=get("NEXLLM_MODEL", ""),
            token_parameter=token_parameter, role=role,
            port=integer("LAB_PORT", 8765, 1024, 65535),
            max_llm_calls=integer("LAB_MAX_LLM_CALLS", 4, 1, 8),
            max_tool_calls=integer("LAB_MAX_TOOL_CALLS", 6, 1, 12),
            max_live_calls=integer("LAB_MAX_LIVE_CALLS", 40, 1, 200),
            max_request_bytes=integer("LAB_MAX_REQUEST_BYTES", 48000, 8000, 96000),
            max_output_tokens=integer("LAB_MAX_OUTPUT_TOKENS", 700, 64, 2000),
            request_timeout=integer("LAB_REQUEST_TIMEOUT_SECONDS", 25, 3, 60),
            turn_timeout=integer("LAB_TURN_TIMEOUT_SECONDS", 75, 5, 180),
            approval_ttl=integer("LAB_APPROVAL_TTL_SECONDS", 120, 10, 600),
        )
