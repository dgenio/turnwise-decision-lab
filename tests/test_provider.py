import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler,HTTPServer
from unittest.mock import patch

from turnwise_lab.core import Request,Source
from turnwise_lab.provider import generate_public_synthetic

class FakeProvider(BaseHTTPRequestHandler):
    def do_POST(self):
        n=int(self.headers['Content-Length'])
        body=json.loads(self.rfile.read(n))
        self.server.seen=body
        msg={'choices':[{'message':{'content':'The synthetic mismatch is a plausible cause [root_cause].'}}],
             'usage':{'prompt_tokens':35,'completion_tokens':13,'total_tokens':48}}
        data=json.dumps(msg).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def log_message(self,*args): pass

class ProviderBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.public=Request(text='Explain the synthetic checkout root cause',sources=(Source('root_cause','checkout root cause','timeout mismatch caused an issue'),))

    def test_requires_explicit_opt_in_even_with_key(self):
        with patch.dict(os.environ,{'TW_TEST_API_KEY':'test'}):
            with self.assertRaises(PermissionError):generate_public_synthetic(self.public,model='test',endpoint='http://127.0.0.1:9/v1/chat/completions',api_key_env='TW_TEST_API_KEY')

    def test_rejects_protected_content(self):
        with self.assertRaises(PermissionError):generate_public_synthetic(Request(text='hello',sensitivity='internal'),model='test',endpoint='https://example.com/v1/chat/completions',allow_remote=True)
        with self.assertRaises(PermissionError):generate_public_synthetic(Request(text='foo@corp.example'),model='test',endpoint='https://example.com/v1/chat/completions',allow_remote=True)
        req=Request(text='hello',sources=(Source('x','nonpublic','context',sensitivity='restricted'),))
        with self.assertRaises(PermissionError):generate_public_synthetic(req,model='test',endpoint='https://example.com/v1/chat/completions',allow_remote=True)

    def test_malformed_or_insecure_endpoint_rejected(self):
        for endpoint in ['http://example.com/v1/chat/completions','file:///etc/passwd','https://user:password@example.com/', 'https://example.com/a?key=b']:
            with self.assertRaises(ValueError):generate_public_synthetic(self.public,model='test',endpoint=endpoint,allow_remote=True)

    def test_real_local_http_handshake_is_not_live_model_inference(self):
        server=HTTPServer(('127.0.0.1',0),FakeProvider)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ,{'TW_TEST_API_KEY':'mock-key'}):
                result=generate_public_synthetic(self.public,model='mock',endpoint=f'http://127.0.0.1:{server.server_port}/v1/chat/completions',api_key_env='TW_TEST_API_KEY',allow_remote=True)
            self.assertTrue(result.actual_provider_call)
            self.assertEqual(result.usage['total_tokens'],48)
            self.assertIsNone(result.cost_usd)
            self.assertEqual(server.seen['model'],'mock')
            self.assertIn('root_cause',server.seen['messages'][1]['content'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

if __name__=='__main__':unittest.main()
