from dataclasses import replace
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
import http.client
import json
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from guardrail_lab.config import Config
from guardrail_lab.guards import GuardError
from guardrail_lab.providers import NexLLMProvider
from guardrail_lab.tools import SCHEMAS


class FakeResponse:
    def __init__(self, data, status=200):
        self.status = status
        self.data = data if isinstance(data, bytes) else json.dumps(data).encode()
    def read1(self, size):
        chunk, self.data = self.data[:size], self.data[size:]
        return chunk
    def isclosed(self):
        return not self.data


class FakeSocket:
    def settimeout(self, value):
        self.timeout = value


class FakeConnection:
    def __init__(self, response):
        self.response, self.sock = response, FakeSocket()
        self.requests, self.closed = [], False
    def connect(self):
        pass
    def request(self, *args, **kwargs):
        self.requests.append((args,kwargs))
    def getresponse(self):
        return self.response
    def close(self):
        self.closed = True


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.config = Config(api_key="TEST_ONLY_NOT_A_REAL_KEY", model="account/model-id")

    def test_chat_wire_format_and_fixed_host(self):
        conn = FakeConnection(FakeResponse({"choices":[{"message":{"role":"assistant","content":"OK"},"finish_reason":"stop"}],"usage":{"total_tokens":12}}))
        with patch("guardrail_lab.providers.http.client.HTTPSConnection", return_value=conn) as factory:
            reply = NexLLMProvider(self.config).complete([{"role":"user","content":"Hello"}], SCHEMAS, self.config.model, time.monotonic()+10)
        self.assertEqual(factory.call_args.args,("www.nexllm.ai",443))
        args, kwargs = conn.requests[0]
        self.assertEqual(args,("POST","/v1/chat/completions"))
        body=json.loads(kwargs["body"])
        self.assertEqual(body["model"],"account/model-id")
        self.assertEqual(body["tools"],SCHEMAS)
        self.assertEqual(body["max_tokens"],700)
        self.assertEqual(kwargs["headers"]["Authorization"],"Bearer TEST_ONLY_NOT_A_REAL_KEY")
        self.assertEqual(reply["usage"]["total_tokens"],12)
        self.assertTrue(conn.closed)

    def test_alternate_output_token_parameter(self):
        conn=FakeConnection(FakeResponse({"choices":[{"message":{"content":"OK"}}]}))
        with patch("guardrail_lab.providers.http.client.HTTPSConnection", return_value=conn):
            NexLLMProvider(replace(self.config,token_parameter="max_completion_tokens")).complete([],SCHEMAS,"test",time.monotonic()+10)
        body=json.loads(conn.requests[0][1]["body"])
        self.assertIn("max_completion_tokens",body)
        self.assertNotIn("max_tokens",body)

    def test_models_shape_and_request(self):
        conn=FakeConnection(FakeResponse({"data":[{"id":"model-b"},{"id":"model-a"},{"id":"<script>"}]}))
        with patch("guardrail_lab.providers.http.client.HTTPSConnection",return_value=conn):
            self.assertEqual(NexLLMProvider(self.config).models(),["model-a","model-b"])
        self.assertEqual(conn.requests[0][0],("GET","/v1/models"))

    def test_redirects_and_errors_do_not_leak_bodies_or_retry(self):
        for status in (302,400,401,403,404,429,500):
            conn=FakeConnection(FakeResponse({"error":"PRIVATE_SERVER_BODY"},status))
            with self.subTest(status=status), patch("guardrail_lab.providers.http.client.HTTPSConnection",return_value=conn):
                with self.assertRaises(GuardError) as result:
                    NexLLMProvider(self.config).models()
                self.assertNotIn("PRIVATE_SERVER_BODY",str(result.exception))
                self.assertEqual(len(conn.requests),1)
                self.assertTrue(conn.closed)

    def test_bad_json_and_oversized_response(self):
        for data in (b"<html>not JSON</html>",b"x"*262145):
            conn=FakeConnection(FakeResponse(data))
            with self.subTest(size=len(data)),patch("guardrail_lab.providers.http.client.HTTPSConnection",return_value=conn):
                with self.assertRaises(GuardError):
                    NexLLMProvider(self.config).models()

    def test_timeout_is_summarized(self):
        conn=FakeConnection(FakeResponse({}))
        conn.connect=lambda: (_ for _ in ()).throw(socket.timeout("private error"))
        with patch("guardrail_lab.providers.http.client.HTTPSConnection",return_value=conn):
            with self.assertRaises(GuardError) as result:
                NexLLMProvider(self.config).models()
        self.assertEqual(result.exception.code,"provider_timeout")
        self.assertNotIn("private error",str(result.exception))

    def test_blank_key_and_unknown_route_stop_before_network(self):
        with patch("guardrail_lab.providers.http.client.HTTPSConnection") as factory:
            with self.assertRaises(GuardError):
                NexLLMProvider(Config()).models()
            with self.assertRaises(GuardError):
                NexLLMProvider(self.config).request("GET","/not-allowed")
        factory.assert_not_called()

    def test_config_rejects_destination_override(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ",{},clear=True):
            file=Path(temp)/".env"
            file.write_text("NEXLLM_BASE_URL=https://example.test/v1\n")
            with self.assertRaises(ValueError):
                Config.load(file)

    def test_content_length_connection_close_transport(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                payload=b'{"data":[{"id":"test-model"}]}'
                self.send_response(200)
                self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(payload)))
                self.send_header("Connection","close")
                self.end_headers()
                self.wfile.write(payload)
            def log_message(self,*args):
                pass
        server=HTTPServer(("127.0.0.1",0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            def local_connection(*args,**kwargs):
                return http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=kwargs["timeout"])
            with patch("guardrail_lab.providers.http.client.HTTPSConnection",side_effect=local_connection):
                self.assertEqual(NexLLMProvider(self.config).models(),["test-model"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
