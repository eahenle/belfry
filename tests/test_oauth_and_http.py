import json
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from notifydock.http import request_json

from notifydock.http import CollectorError, parse_next_link
from notifydock.model import valid_url
from notifydock.oauth import access_token, store_token


class FakeKeychain:
    def __init__(self): self.values={}
    def set(self, key, val): self.values[key]=val
    def get(self, key): return self.values[key]


class OAuthTests(unittest.TestCase):
    def test_valid_urls_only(self):
        self.assertTrue(valid_url('https://example.com/mail'))
        for link in ('http://example.com','javascript:alert(1)','file:///etc/passwd',
                     'https://user:pass@example.com/', 'https://'):
            self.assertFalse(valid_url(link))

    def test_oauth_token_refresh_no_file(self):
        kc=FakeKeychain()
        store_token(kc,'ref',{'access_token':'expired','refresh_token':'refresh','expires_in':0},
                    client_id='public-client',token_url='https://login.microsoftonline.com/common/oauth2/v2.0/token',
                    scope='offline_access Mail.ReadBasic')
        with patch('notifydock.oauth.form_post',return_value={'access_token':'new','expires_in':3600}) as post:
            self.assertEqual(access_token(kc,'ref'),'new')
            self.assertEqual(access_token(kc,'ref'),'new')
            self.assertEqual(post.call_count,1)
            self.assertEqual(post.call_args.args[1]['refresh_token'],'refresh')
            self.assertEqual(json.loads(kc.get('ref'))['refresh_token'],'refresh')

    def test_authorization_not_forwarded_on_redirect(self):
        received=[]
        class Landing(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append(self.headers.get('Authorization'))
                self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(b'{}')
            def log_message(self,*args): pass
        class Start(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header('Location', f'http://127.0.0.1:{land.server_port}/')
                self.end_headers()
            def log_message(self,*args): pass
        land=ThreadingHTTPServer(('127.0.0.1',0),Landing)
        start=ThreadingHTTPServer(('127.0.0.1',0),Start)
        workers=[]
        try:
            for server in (land,start):
                t=Thread(target=server.serve_forever,daemon=True); t.start(); workers.append(t)
            with self.assertRaises(CollectorError):
                request_json(f'http://127.0.0.1:{start.server_port}', {'Authorization':'Bearer should-not-leak'})
            self.assertEqual(received,[])
        finally:
            land.shutdown(); start.shutdown()
            land.server_close(); start.server_close()

    def test_reject_cross_host_pagination(self):
        link='<https://github.com.evil.example/notifications?page=2>; rel="next"'
        with self.assertRaises(CollectorError): parse_next_link(link,'https://api.github.com/notifications?')


if __name__=='__main__': unittest.main()
