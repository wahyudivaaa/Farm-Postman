"""
Postman AI Gateway — OpenAI-compatible proxy over Postman Agent Mode /_gw/chat.

Turns Postman's free Agent Mode (50k credits/mo on free accounts) into a drop-in
OpenAI-compatible /v1/chat/completions endpoint usable by any AI agent
(OpenCode, Hermes, Cline, etc).

Auth: session cookies (postman.sid) + optional access token via iapub.

Usage:
    python postman_gateway.py --cookies live_cookies.json --workspace https://<user>-<id>.postman.co --port 9121
    curl http://localhost:9121/v1/models
    curl http://localhost:9121/v1/chat/completions -d '{"model":"claude-opus-4-8","messages":[{"role":"user","content":"hi"}]}'
"""
import json, os, sys, time, threading, uuid, argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "codebuddy-farm"))
from curl_cffi import requests as crequests

APP_VER = "12.15.4-260616-1202"

# Postman model key -> OpenAI-friendly id
MODEL_ALIASES = {
    "claude-opus-4-8": "CLAUDE_OPUS_48_BEDROCK",
    "claude-opus-4-7": "CLAUDE_OPUS_47_BEDROCK",
    "claude-opus-4-5": "CLAUDE_OPUS_45_BEDROCK",
    "claude-sonnet-4-6": "CLAUDE_46_SONNET_BEDROCK",
    "claude-sonnet-4-5": "CLAUDE_45_SONNET_BEDROCK",
    "gpt-5.6-sol": "GPT_56_SOL",
    "gpt-5.6-terra": "GPT_56_TERRA",
    "gpt-5.6-luna": "GPT_56_LUNA",
    "gpt-5.5": "GPT_55",
    "gpt-5.4": "GPT_54",
}
PM_KEY_TO_OPENAI = {v: k.replace("_", "-").lower() for k, v in MODEL_ALIASES.items()}
PM_KEY_TO_OPENAI.update({v: k for k, v in MODEL_ALIASES.items()})  # both directions for lookup

class PostmanGateway:
    def __init__(self, cookies_path, workspace):
        self.cookies = json.load(open(cookies_path))
        self.psid = self.cookies.get("postman.sid", "")
        self.ws = workspace.rstrip("/")
        self.subdomain = self.ws.replace("https://", "").split("/")[0]
        self.s = crequests.Session(impersonate="chrome131")
        self._conv_cache = {}

    def hdrs(self, accept="text/event-stream"):
        return {"Cookie": f"postman.sid={self.psid}", "Content-Type": "application/json", "Accept": accept,
                "x-app-version": APP_VER, "x-pstmn-req-service": "agent-mode-service",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
                "Origin": self.ws, "Referer": self.ws + "/"}

    def list_models(self):
        r = self.s.get(f"{self.ws}/_gw/config", headers=self.hdrs("application/json"), timeout=60)
        return r.json().get("models", [])

    def chat(self, messages, model=None, stream=False, session_key="default"):
        # map openai model -> postman key
        pm_model = MODEL_ALIASES.get(model, model) if model else None
        query = messages[-1]["content"] if messages else ""
        conv_id = self._conv_cache.get(session_key)
        body = {
            "input": {"chatType": "USER_QUERY", "query": query, "toolResponse": "", "useCase": None,
                      "conversationId": conv_id, "agent": None, "product": "workspace_v12", "startedFrom": "CHAT_INPUT"},
            "platform": "WEB",
            "clientTools": {"nativeToolsHash": f"clienttools-workspace_v12-browser-{APP_VER}-d5808662718f",
                            "excludedTools": ["listDatasets", "createDataset", "previewDataset", "queryDatasetView"]},
            "clientKBTerms": {"nativeTermsHash": f"kbterms-workspace_v12-browser-{APP_VER}-4755650f241c",
                              "excludedKBTerms": ["DATASETS"]},
            "mandatoryContext": {"workspaceId": self.cookies.get("_pm.uid", "").split(".")[0] or "0"},
            "selectedContext": [], "backgroundContext": [], "availableSkills": [],
            "devModeOptions": {"selectedModel": pm_model, "isParallelToolCallingSupported": True, "autoRun": False,
                               "supportsAskUser": False, "supportsActionRecommendations": True,
                               "useThinkingModeIfAvailable": True, "thinkingLevel": "low"},
        }
        if stream:
            return self._stream(body, pm_model)
        return self._nonstream(body, pm_model)

    def _stream(self, body, pm_model):
        collected = []
        final_model = pm_model
        try:
            with self.s.stream("POST", f"{self.ws}/_gw/chat", json=body, headers=self.hdrs(), timeout=180) as resp:
                for line in resp.iter_lines():
                    if not line: continue
                    txt = line.decode(errors="ignore")
                    if not txt.startswith("data:"): continue
                    try: ev = json.loads(txt[5:])
                    except: continue
                    et = ev.get("eventType")
                    if et == "textChunk" and ev.get("data", {}).get("textContent"):
                        collected.append(ev["data"]["textContent"])
                    elif et == "conversation" and ev.get("data", {}).get("id"):
                        pass
                    if et == "info" and "llm-call-stream-end" in ev.get("data", {}).get("message", ""):
                        break
            return {"status": 200, "text": "".join(collected)}
        except Exception as e:
            return {"status": 500, "error": str(e)}

    def _nonstream(self, body, pm_model):
        # non-streaming chat uses no ?stream — SSE still returns; collect all
        return self._stream(body, pm_model)

GW = None

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj, is_event=False):
        if is_event:
            data = obj if isinstance(obj, str) else json.dumps(obj)
            body = data.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
        else:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            models = GW.list_models()
            data = {"object": "list", "data": [{"id": PM_KEY_TO_OPENAI.get(m.get("key"), m.get("key")),
                    "object": "model", "owned_by": "postman", "displayName": m.get("displayName")}
                    for m in models]}
            self._send(200, data)
        elif self.path == "/health":
            self._send(200, {"ok": True, "service": "postman-agent-mode"})
        else:
            self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if not self.path.startswith("/v1/chat/completions"):
            return self._send(404, {"error": {"message": "not found"}})
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        model = body.get("model", "claude-sonnet-4-6")
        stream = bool(body.get("stream", False))
        messages = body.get("messages", [])
        res = GW.chat(messages, model=model, stream=stream)
        if "error" in res and not res.get("text"):
            return self._send(500, {"error": {"message": f"postman upstream: {res['error']}"}})
        text = res.get("text", "")
        if stream:
            cid = "chatcmpl-" + uuid.uuid4().hex
            # send chunks
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for i in range(0, len(text), 30):
                chunk = text[i:i+30]
                ev = {"id": cid, "object": "chat.completion.chunk", "model": model,
                      "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}]}
                self.wfile.write(("data: " + json.dumps(ev) + "\n\n").encode())
                self.wfile.flush()
            final = {"id": cid, "object": "chat.completion.chunk", "model": model,
                     "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            self.wfile.write(("data: " + json.dumps(final) + "\n\ndata: [DONE]\n\n").encode())
        else:
            self._send(200, {"id": "chatcmpl-" + uuid.uuid4().hex, "object": "chat.completion", "model": model,
                             "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                             "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cookies", required=True)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--port", type=int, default=9121)
    a = ap.parse_args()
    global GW
    GW = PostmanGateway(a.cookies, a.workspace)
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    print(f"Postman AI Gateway on :{a.port}")
    print(f"  /v1/models            (list premium models)")
    print(f"  /v1/chat/completions  (OpenAI-compatible chat)")
    srv.serve_forever()

if __name__ == "__main__":
    main()