from pathlib import Path
import http.client
import json
import tempfile
import threading
import unittest
from guardrail_lab.config import Config
from guardrail_lab.server import LabServer


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.server=LabServer(Config(audit_path=Path(cls.temp.name)/"audit.jsonl"),port=0)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.origin=f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.temp.cleanup()

    def request(self,method,path,body=None,headers=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=5)
        hdrs={"Origin":self.origin}
        if body is not None:
            hdrs["Content-Type"]="application/json"
        hdrs.update(headers or {})
        conn.request(method,path,None if body is None else json.dumps(body),headers=hdrs)
        response=conn.getresponse()
        data=response.read()
        result=(response.status,dict(response.getheaders()),data)
        conn.close()
        return result

    def auth(self):
        status,headers,data=self.request("GET","/api/bootstrap")
        self.assertEqual(status,200)
        bootstrap=json.loads(data)
        return {"Cookie":headers["Set-Cookie"].split(";",1)[0],"X-Lab-CSRF":bootstrap["csrf"]},bootstrap

    def test_static_files_csp_and_no_arbitrary_files(self):
        status,headers,data=self.request("GET","/")
        self.assertEqual(status,200)
        self.assertIn("script-src 'self'",headers["Content-Security-Policy"])
        self.assertIn(b"Guardrail Lab",data)
        for path in ("/.env","/data/orders.json","/../.env","/logs/audit.jsonl"):
            self.assertEqual(self.request("GET",path)[0],404)

    def test_cross_origin_and_invalid_host_rejected(self):
        self.assertEqual(self.request("GET","/",headers={"Host":"evil.example"})[0],403)
        self.assertEqual(self.request("GET","/api/bootstrap",headers={"Origin":"https://evil.example"})[0],403)
        headers,_=self.auth()
        headers["Origin"]="https://evil.example"
        self.assertEqual(self.request("POST","/api/reset",{},headers)[0],403)

    def test_csrf_and_session_required(self):
        headers,_=self.auth()
        headers["X-Lab-CSRF"]="incorrect"
        self.assertEqual(self.request("POST","/api/reset",{},headers)[0],403)
        self.assertEqual(self.request("POST","/api/reset",{})[0],400)

    def test_http_chat_approval_tamper_replay_and_reset(self):
        headers,_=self.auth()
        body={"prompt":"Refund HKD 80 for ORD-1001","mode":"demo","model":"","remember":False}
        code,_,data=self.request("POST","/api/chat",body,headers)
        self.assertEqual(code,200)
        r=json.loads(data)
        self.assertEqual(r["status"],"approval_required")
        approval_id=r["pending"]["approval_id"]
        tampered={"approval_id":approval_id,"approve":True,"amount_hkd":120}
        self.assertEqual(self.request("POST","/api/decide",tampered,headers)[0],400)
        _,_,data=self.request("POST","/api/decide",{"approval_id":approval_id,"approve":True},headers)
        approved=json.loads(data)
        self.assertEqual(approved["ledger"][0]["amount_hkd"],80)
        _,_,data=self.request("POST","/api/decide",{"approval_id":approval_id,"approve":True},headers)
        self.assertEqual(json.loads(data)["status"],"blocked")
        self.server.engine.live_attempts=7
        _,_,data=self.request("POST","/api/reset",{},headers)
        result=json.loads(data)
        self.assertEqual(result["ledger"],[])
        self.assertEqual(result["live_calls"],7)
        self.server.engine.live_attempts=0

    def test_no_key_or_secret_exposed_in_bootstrap(self):
        _,bootstrap=self.auth()
        self.assertNotIn("api_key",bootstrap)
        self.assertFalse(bootstrap["key_configured"])

    def test_oversized_body_rejected(self):
        headers,_=self.auth()
        self.assertEqual(self.request("POST","/api/chat",{"prompt":"a"*13000},headers)[0],413)

    def test_busy_controller_rejects_concurrent_mutation(self):
        headers,_=self.auth()
        with self.server.lock:
            self.assertEqual(self.request("POST","/api/reset",{},headers)[0],409)


if __name__ == "__main__":
    unittest.main()
