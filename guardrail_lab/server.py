"""Loopback-only teaching server with fixed routes, session cookies, and CSRF checks."""
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
import time
from .config import ROOT
from .guards import GuardError
from .harness import Engine, Session
from .providers import strict_json


class LabServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, config, port=None, engine=None):
        self.config = config
        self.engine = engine or Engine(config)
        self.sessions = {}
        self.lock = threading.Lock()
        self.last_models_at = 0.0
        super().__init__(("127.0.0.1", config.port if port is None else port), Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "GuardrailLab/1.0"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_):
        pass  # Avoid recording URLs, session identifiers, or user text in terminal logs.

    def reply(self, status, content, mime="application/json; charset=utf-8", cookie=None):
        if not isinstance(content, bytes):
            content = json.dumps(content, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header("X-Frame-Options", "DENY")
        if cookie:
            self.send_header("Set-Cookie", "lab_session=" + cookie + "; HttpOnly; SameSite=Strict; Path=/")
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def valid_origin(self, mutation=False):
        port = self.server.server_port
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if len(self.headers.get_all("Host", [])) != 1 or self.headers.get("Host") not in allowed:
            return False
        origin = self.headers.get("Origin")
        if (mutation and not origin) or (origin and origin not in {"http://" + h for h in allowed}):
            return False
        return self.headers.get("Sec-Fetch-Site", "") != "cross-site"

    def session(self, create=False):
        now = time.monotonic()
        stale = [sid for sid, s in self.server.sessions.items() if now - s.last_used > 1800]
        for sid in stale:
            del self.server.sessions[sid]
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            sid = cookies["lab_session"].value if "lab_session" in cookies else ""
        except Exception:
            sid = ""
        session = self.server.sessions.get(sid)
        if session:
            session.last_used = now
            return sid, session, False
        if not create:
            raise GuardError("Permission", "session_missing", "Session expired or server restarted. Refresh the page.")
        if len(self.server.sessions) >= 32:
            raise GuardError("Budget", "session_limit", "Session limit reached. Restart the local lab to clear unused sessions.")
        sid, session = secrets.token_urlsafe(32), Session()
        self.server.sessions[sid] = session
        return sid, session, True

    def do_GET(self):
        if not self.valid_origin():
            return self.reply(403, {"error": "Local origin required."})
        static = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/styles.css": ("styles.css", "text/css; charset=utf-8")}
        if self.path in static:
            name, mime = static[self.path]
            return self.reply(200, (ROOT / "web" / name).read_bytes(), mime)
        if self.path != "/api/bootstrap":
            return self.reply(404, {"error": "Route not found."})
        if not self.server.lock.acquire(blocking=False):
            return self.reply(409, {"error": "The agent is busy. Wait for the current turn."})
        try:
            sid, session, new = self.session(create=True)
            c = self.server.config
            return self.reply(200, {"csrf": session.csrf, "key_configured": bool(c.api_key),
                "model": c.model, "role": c.role, "base_url": c.base_url,
                "limits": {"rounds": c.max_llm_calls, "tools": c.max_tool_calls,
                    "output_tokens": c.max_output_tokens, "request_bytes": c.max_request_bytes,
                    "deadline_seconds": c.turn_timeout}, **self.server.engine.state(session)}, cookie=sid if new else None)
        except GuardError as error:
            self.reply(400, {"error": error.message})
        finally:
            self.server.lock.release()

    def do_POST(self):
        if not self.valid_origin(mutation=True):
            return self.reply(403, {"error": "Local same-origin request required."})
        if self.path not in {"/api/chat", "/api/decide", "/api/reset", "/api/memory/clear", "/api/models"}:
            return self.reply(404, {"error": "Route not found."})
        if self.headers.get_content_type() != "application/json" or self.headers.get("Transfer-Encoding"):
            return self.reply(415, {"error": "Use a bounded JSON request."})
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not lengths[0].isdigit() or not 0 < int(lengths[0]) <= 12000:
            return self.reply(413, {"error": "Request body must be 1–12,000 bytes."})
        try:
            body = strict_json(self.rfile.read(int(lengths[0])).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, UnicodeError, TimeoutError, OSError, RecursionError):
            return self.reply(400, {"error": "Invalid JSON request."})
        if not self.server.lock.acquire(blocking=False):
            return self.reply(409, {"error": "The agent is busy. Wait for the current turn."})
        try:
            _, session, _ = self.session()
            csrf = self.headers.get("X-Lab-CSRF", "")
            if not secrets.compare_digest(csrf, session.csrf):
                return self.reply(403, {"error": "Session check failed. Refresh the page."})
            engine = self.server.engine
            if self.path == "/api/chat":
                if set(body) != {"prompt", "mode", "model", "remember"} or not all(isinstance(body[k], str) for k in ("prompt", "mode", "model")):
                    return self.reply(400, {"error": "Invalid chat fields."})
                return self.reply(200, engine.run(session, **body))
            if self.path == "/api/decide":
                if set(body) != {"approval_id", "approve"}:
                    return self.reply(400, {"error": "Only the stored approval ID and decision are accepted."})
                return self.reply(200, engine.decide(session, **body))
            if body:
                return self.reply(400, {"error": "This endpoint expects an empty JSON object."})
            if self.path == "/api/reset":
                engine.event(session, "Memory", "passed", "sandbox_reset", "Chat memory, pending proposal, and simulated ledger cleared. Process live budget retained.")
                session.history.clear()
                session.pending = None
                session.refunded.clear()
                session.ledger.clear()
                return self.reply(200, engine.state(session))
            if self.path == "/api/memory/clear":
                session.history.clear()
                engine.event(session, "Memory", "passed", "memory_cleared", "Conversation memory explicitly cleared from RAM.")
                return self.reply(200, engine.state(session))
            if time.monotonic() - self.server.last_models_at < 10:
                return self.reply(429, {"error": "Wait 10 seconds between model-list requests."})
            self.server.last_models_at = time.monotonic()
            return self.reply(200, {"models": engine.live.models()})
        except GuardError as error:
            self.reply(400, {"error": error.message})
        except Exception:
            self.reply(500, {"error": "The local request failed safely. No automatic retry was made."})
        finally:
            self.server.lock.release()
