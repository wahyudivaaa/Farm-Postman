"""
Postman AI Gateway Proxy — wraps the authenticated Postman runtime endpoints so any
OpenAI-compatible agent can use them.

Status: uses ra.gw handshake token + cloud-agent gateway. Acts as OpenAI-compatible
/v1/chat/completions bridge. Credentials come from an authenticated session (cookies).

Usage:
  python postman_proxy.py --cookies fresh_cookies.json --port 9120
"""
import json, os, sys, time, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.request, urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "codebuddy-farm"))
from curl_cffi import requests as crequests

class PostmanGateway:
    def __init__(self, cookies_path):
        self.cookies = json.load(open(cookies_path))
        self.cookie_str = "; ".join(f"{k}={v}" for k,v in self.cookies.items())
        self.session = crequests.Session(impersonate="chrome131")
        self.session.headers.update({"User-Agent":"Mozilla/5.0","Accept":"application/json"})
        self.token = None
        self.token_exp = 0

    def get_token(self, force=False):
        if not force and self.token and time.time() < self.token_exp - 60:
            return self.token
        r = self.session.get("https://ra.gw.postman.com/v1/handshake/token?agent=CLOUD",
                             headers={"Cookie": self.cookie_str}, timeout=30)
        if r.status_code == 200:
            j = r.json()
            self.token = j.get("token")
            # exp in JWT ~1800s; cache 15 min
            self.token_exp = time.time() + 900
            return self.token
        raise RuntimeError(f"handshake failed: {r.status_code} {r.text[:100]}")

    def chat(self, messages, model="gpt-5.6-sol", stream=False):
        tok = self.get_token()
        # Try the cloud-agent /v1/request with proper AI SDK LLMRequest body
        body = {
            "url": "https://api.anthropic.com/v1/messages" if "claude" in model else "https://api.openai.com/v1/chat/completions",
            "config": {"model": model, "provider": "gateway"},
            "settings": {"temperature": 0.7, "maxTokens": 2048},
            "messages": messages,
        }
        r = self.session.post("https://cloud-agent.gw.postman.com/v1/request",
                              json=body,
                              headers={"Authorization": f"Bearer {tok}", "Cookie": self.cookie_str},
                              timeout=60)
        return r

PROXY=None

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, code, obj):
        d = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(d))); self.end_headers()
        self.wfile.write(d)
    def do_GET(self):
        if self.path.startswith("/v1/models"):
            self._json(200, {"object":"list","data":[
                {"id":"gpt-5.6-sol","object":"model","owned_by":"postman"},
                {"id":"claude-opus-5","object":"model","owned_by":"postman"},
                {"id":"claude-sonnet-4-5","object":"model","owned_by":"postman"},
            ]})
        elif self.path == "/health": self._json(200, {"ok":True})
        else: self._json(404, {"error":"not found"})
    def do_POST(self):
        if self.path.startswith("/v1/chat/completions"):
            try:
                n = int(self.headers.get("Content-Length",0))
                body = json.loads(self.rfile.read(n) or b"{}")
                model = body.get("model","gpt-5.6-sol")
                messages = body.get("messages",[])
                r = PROXY.chat(messages, model)
                content = (r.text or "")[:500]
                print(f"[chat] {model} -> {r.status_code}: {content[:120]}")
                if r.status_code != 200:
                    self._json(502, {"error":{"message":f"upstream {r.status_code}: {content[:200]}","type":"upstream"}})
                    return
                # if upstream already OpenAI-compatible pass through, else wrap
                try:
                    j = r.json()
                    self._json(200, j)
                except Exception:
                    self._json(200, {"id":"chatcmpl-postman","object":"chat.completion","model":model,
                                     "choices":[{"index":0,"message":{"role":"assistant","content":content},"finish_reason":"stop"}],
                                     "usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}})
            except Exception as e:
                self._json(500, {"error":{"message":str(e),"type":"internal"}})
        else:
            self._json(404, {"error":"not found"})

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cookies", required=True)
    ap.add_argument("--port", type=int, default=9120)
    a = ap.parse_args()
    global PROXY
    PROXY = PostmanGateway(a.cookies)
    # warm token
    try:
        t = PROXY.get_token(); print("token ready:", t[:30], "...")
    except Exception as e:
        print("token warn failed:", e)
    srv = HTTPServer(("0.0.0.0", a.port), Handler)
    print(f"Postman proxy on :{a.port}  (OpenAI-compatible /v1/chat/completions)")
    srv.serve_forever()

if __name__ == "__main__":
    main()