"""Readiness check. No external requests and no credential values are printed."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    if sys.version_info < (3, 11):
        print("FAIL: Python 3.11 or newer is required.")
        return 1
    from guardrail_lab.config import Config
    from guardrail_lab.tools import ToolBox
    try:
        config = Config.load()
        tools = ToolBox()
        for file in ("web/index.html", "web/app.js", "web/styles.css"):
            if not (ROOT / file).is_file():
                raise ValueError("A web asset is missing. Extract the entire ZIP again.")
        config.audit_path.parent.mkdir(parents=True, exist_ok=True)
        check = config.audit_path.parent / ".write_check"
        check.write_text("check", encoding="utf-8")
        check.unlink()
    except (ValueError, OSError) as error:
        print("FAIL:", str(error))
        return 1
    print("PASS: Python", sys.version.split()[0])
    print("PASS: Standard-library dependencies, web assets, demo data, and writable logs/")
    print("PASS: Fixed HTTPS NexLLM endpoint; role =", config.role)
    print("Demo orders:", ", ".join(tools.orders))
    print("NexLLM key:", "configured (hidden)" if config.api_key else "blank; offline demo is ready")
    print("NexLLM model:", "configured" if config.model else "blank; choose an account model in the UI or .env")
    print("Live API connectivity has NOT been tested by this check.")
    print(f"Next: python app.py, then open http://127.0.0.1:{config.port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
