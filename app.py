"""Run: python app.py. Then open http://127.0.0.1:8765."""
import sys


def main():
    if sys.version_info < (3, 11):
        print("Please install Python 3.11 or newer, then run this file again.")
        return 1
    from guardrail_lab.config import Config
    from guardrail_lab.server import LabServer
    try:
        config = Config.load()
        server = LabServer(config)
    except (ValueError, OSError):
        print("Startup failed. Check .env values, file permissions, and whether LAB_PORT is already in use.")
        print("Run: python scripts/health_check.py")
        return 1
    print("\nGUARDRAIL LAB | Local classroom agent")
    print(f"Open http://127.0.0.1:{server.server_port}")
    print("Offline demo is ready. NexLLM key: " + ("configured" if config.api_key else "blank (add it in .env for live mode)"))
    print("Press Ctrl+C to stop. No real payments are available.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nLab stopped. In-memory sessions and simulated refunds are discarded.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
