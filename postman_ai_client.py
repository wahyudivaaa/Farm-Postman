"""
Postman AI Gateway Client — clean OpenAI-adjacent client for the Agent Mode /_gw gateway.

Wraps the reverse-engineered Postman AI endpoints into a usable client:
  * access token   -> iapub.postman.co/api/sessions/current
  * conversation   -> /_gw/conversation
  * models         -> /_gw/config
  * AI suggestions -> /_gw/list-context-suggestions
  * chat           -> /_gw/chat  (SSE stream)

Usage:
  python postman_ai_client.py --cookies <session_cookies.json> --workspace <https://<user>-<id>.postman.co>
"""
import json, os, sys, argparse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "codebuddy-farm"))
from curl_cffi import requests as crequests

class PostmanAIClient:
    def __init__(self, cookies_path, workspace):
        self.cookies = json.load(open(cookies_path))
        self.cookie_str = "; ".join(f"{k}={v}" for k,v in self.cookies.items())
        self.ws = workspace.rstrip("/")
        self.s = crequests.Session(impersonate="chrome131")
        self.s.headers.update({"User-Agent":"Mozilla/5.0","Accept":"application/json","Cookie":self.cookie_str})

    # --- access token ---
    def access_token(self):
        r = self.s.get("https://iapub.postman.co/api/sessions/current", timeout=40)
        return r.json()["session"]["token"]

    def _gw_headers(self):
        return {"User-Agent":"Mozilla/5.0","Accept":"text/event-stream","Cookie":self.cookie_str,
                "Content-Type":"application/json","Origin":self.ws,"Referer":self.ws+"/",
                "x-pstmn-req-service":"agent-mode-service","x-app-version":"12.25.5-260826-0538"}

    # --- gateway calls ---
    def create_conversation(self, title="chat"):
        r = self.s.post(f"{self.ws}/_gw/conversation", json={"title":title}, headers=self._gw_headers(), timeout=60)
        return r.json()["data"]["id"]

    def list_conversations(self):
        r = self.s.get(f"{self.ws}/_gw/conversation", headers=self._gw_headers(), timeout=60)
        return r.json()

    def models(self):
        r = self.s.get(f"{self.ws}/_gw/config", headers=self._gw_headers(), timeout=60)
        return r.json()

    def suggestions(self, prompt):
        r = self.s.post(f"{self.ws}/_gw/list-context-suggestions", json={"userPrompt":prompt},
                        headers=self._gw_headers(), timeout=60)
        return r.json()

    def chat(self, conversation_id, message, model=None, stream=True):
        """Call /_gw/chat. Legacy note: /_gw/chat currently returns INPUT_VALIDATION_ERROR:Forbidden
        unless the exact internal body is supplied — documented here for completeness."""
        body = {"conversationId":conversation_id, "message":message}
        if model: body["model"] = model
        hdrs = self._gw_headers()
        path = f"{self.ws}/_gw/chat" + ("" if stream else "?stream=false")
        if stream:
            with self.s.stream("POST", path, json=body, headers=hdrs, timeout=120) as resp:
                out = []
                for line in resp.iter_lines():
                    if line:
                        t = line.decode(errors="ignore")
                        out.append(t)
                        if data_is_error(t): break
                return {"status":resp.status_code, "events":out}
        r = self.s.post(path, json=body, headers=hdrs, timeout=120)
        return {"status":r.status_code, "body":r.text}

def data_is_error(line):
    return "INPUT_VALIDATION_ERROR" in line or "DONE" in line

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cookies", required=True)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--conversation-title", default="chat")
    a = ap.parse_args()
    c = PostmanAIClient(a.cookies, a.workspace)
    tok = c.access_token()
    print("access token:", tok[:25], "...")
    print("\n=== models ===")
    cfg = c.models()
    for m in cfg.get("models", [])[:8]:
        print(f"  {m.get('key')} — {m.get('displayName')}")
    print("  ... total", len(cfg.get("models", [])), "models")

if __name__ == "__main__":
    main()