"""Inject all existing Postman sessions into the server pool, deriving subdomain via iapub."""
import json, os, sys, glob, subprocess, re
sys.path.insert(0, r"D:\Project\codebuddy-farm")
from curl_cffi import requests as crequests

BASE = r"D:\Project\Farm Postman"
SERVER = "http://127.0.0.1:9121"
API_KEY = "postman-default-key"

cookiefiles = ["account_session.json","robust_result.json","session_cookies.json",
               "end_session.json","all_cookies.json","fresh_cookies.json"]

def unify(d):
    if isinstance(d, dict):
        if "pm_cookies" in d and isinstance(d["pm_cookies"],dict): return d["pm_cookies"]
        if "pm" in d and isinstance(d["pm"],dict): return d["pm"]
    return d

def get_subdomain(psid):
    # iapub /api/sessions/current returns session info (may include subdomain via identity)
    try:
        r = crequests.get("https://iapub.postman.co/api/sessions/current",
                          headers={"Cookie": f"postman.sid={psid}"}, impersonate="chrome131", timeout=40)
        j = r.json()
        sess = j.get("session", {})
        # try to find subdomain
        ident = sess.get("identity", {})
        user = ident.get("user",""); team = ident.get("team","")
        # derive subdomain from user/team if possible
        if user and team:
            return f"{user}-{team}.postman.co" if user.isdigit() else f"{user}.postman.co"
        return ""
    except Exception as e:
        return ""

seen = set()
added = 0
for cf in cookiefiles:
    p = os.path.join(BASE, cf)
    try:
        d = json.load(open(p, encoding="utf-8"))
        ck = unify(d)
        sid = ck.get("postman.sid","")
        if not sid or sid in seen: continue
        seen.add(sid)
        # get subdomain
        sub = get_subdomain(sid)
        if not sub:
            # try to find in file url/uid
            uid = ck.get("_pm.uid","")
            sub = f"{sid[:9]}.postman.co"  # fallback guess
        label = cf.replace(".json","")
        r = subprocess.run(["curl","-s","-m","15","-X","POST",f"{SERVER}/api/accounts",
            "-H",f"Authorization: Bearer {API_KEY}","-H","Content-Type: application/json",
            "-d",json.dumps({"label":label,"postman_sid":sid,"workspace_subdomain":sub})],
            capture_output=True,text=True,timeout=25)
        try:
            j = json.loads(r.stdout)
            if j.get("ok"):
                added += 1
                print(f"✅ {label} sub={sub}")
            else:
                print(f"⚠️ {label}: {j.get('error','?')}")
        except:
            print(f"❌ {label}: {r.stdout[:60]}")
    except Exception as e:
        print(f"ERR {cf}: {e}")
print(f"\nAdded {added} accounts")