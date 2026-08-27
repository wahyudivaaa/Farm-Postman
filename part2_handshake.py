"""Part 2: curl_cffi handshake using a cookies JSON file. Run with a venv that has curl_cffi.

Usage: python part2_handshake.py <cookies.json>
"""
import json, sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "codebuddy-farm"))
from curl_cffi import requests as crequests

cookies_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "fresh_cookies.json")
cookies = json.load(open(cookies_path))
cookie_str="; ".join(f"{k}={v}" for k,v in cookies.items())
print("cookie len:", len(cookie_str), "| iam:", cookies.get("postman.iam.sid","")[:20])

s=crequests.Session(impersonate="chrome131")
s.headers.update({"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
                  "Accept":"application/json"})
print("\n=== HANDSHAKE (curl_cffi) ===")
for u in ["https://ra.gw.postman.com/v1/handshake/token?agent=CLOUD",
          "https://ra.gw.postman.com/v1/handshake/token?agent=WS",
          "https://id.gw.postman.com/continue"]:
    try:
        r=s.get(u, headers={"Cookie":cookie_str}, timeout=30)
        print(f"\n[{r.status_code}] {u}")
        print("   ", (r.text or "")[:300])
    except Exception as e:
        print(f"[ERR] {u}: {str(e)[:100]}")
# cloud-agent ws via http (probe)
try:
    r=s.get("https://cloud-agent.gw.postman.com/ws", headers={"Cookie":cookie_str,"Upgrade":"websocket","Connection":"Upgrade"}, timeout=20)
    print(f"\n[{r.status_code}] cloud-agent/ws")
    print("   ", (r.text or "")[:200])
except Exception as e:
    print(f"[ERR] cloud-agent: {str(e)[:100]}")