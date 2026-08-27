"""
Postman mass farmer — 1000 accounts.
Creates a temp-mail (FlashMail), runs robust_full.py (CloakBrowser signup+verify+workspace),
extracts postman.sid, and injects the account into the server pool (POST /api/accounts).
Uses N parallel workers (CloakBrowser is heavy; default 2).
"""
import os, sys, json, time, random, string, subprocess, re, concurrent.futures

BASE = os.path.dirname(os.path.abspath(__file__))
MAIL_API = os.environ.get("MAIL_API", "https://mail.flashdev.org/api/public/v1")
MAIL_KEY = os.environ.get("MAIL_API_KEY", "CHANGE_ME_cmf_v1_your_flashmail_key_here")
SERVER = "http://127.0.0.1:9121"
API_KEY = "postman-default-key"
VENV = r"D:\Project\captcha-solver\.venv\Scripts\python.exe"

def rand_name(n=8):
    return "u" + "".join(random.choice(string.ascii_lowercase+string.digits) for _ in range(n))

def gen_email():
    return f"{rand_name(10)}@devflash.online"

def make_mail(username):
    # create mailbox via API
    r = subprocess.run(["curl","-s","-m","20","-X","POST",f"{MAIL_API}/create_user",
        "-H",f"Authorization: Bearer {MAIL_KEY}","-H","Content-Type: application/json",
        "-d",json.dumps({"username":username,"domain":"devflash.online","name":"flash"})],
        capture_output=True,text=True,timeout=30)
    try:
        j=json.loads(r.stdout)
        return j.get("ok", False), j.get("data",{}).get("email", f"{username}@devflash.online")
    except: return False, f"{username}@devflash.online"

def farm_one(i, counter):
    username = rand_name(10)
    email = f"{username}@devflash.online"
    password = "Fp" + "".join(random.choice(string.ascii_letters+string.digits) for _ in range(8)) + "!7"
    make_mail(username)
    out_path = os.path.join(BASE, f"farm_out_{i}.json")
    env = {**os.environ, "MAIL_API": MAIL_API, "MAIL_API_KEY": MAIL_KEY, "FARM_OUT": out_path}
    for attempt in range(3):
        try:
            r = subprocess.run([VENV, os.path.join(BASE,"robust_full.py"), email, username, password],
                capture_output=True, text=True, timeout=280, env=env, cwd=BASE)
            res = {}
            try: res = json.load(open(out_path))
            except: pass
            cookies = res.get("pm", {})
            sid = cookies.get("postman.sid","")
            if sid:
                sub = ""
                u = res.get("url","")
                m = re.search(r"https://([a-z0-9-]+)\.postman\.co", u)
                if m: sub = m.group(1) + ".postman.co"
                if not sub:
                    for k,v in cookies.items():
                        if "uid" in k.lower(): sub = str(v)[:40]
                subprocess.run(["curl","-s","-m","15","-X","POST",f"{SERVER}/api/accounts",
                    "-H",f"Authorization: Bearer {API_KEY}","-H","Content-Type: application/json",
                    "-d",json.dumps({"label":f"acct{i}","postman_sid":sid,"workspace_subdomain":sub})],
                    capture_output=True,text=True,timeout=25)
                try: os.remove(out_path)
                except: pass
                return {"i":i,"email":email,"status":"OK","sid":sid[:12],"sub":sub}
            # not ok — retry unless it clearly failed verify 3x
        except Exception as e:
            pass
        time.sleep(2)
    try: os.remove(out_path)
    except: pass
    return {"i":i,"email":email,"status":"FAIL"}

def main():
    workers = int(sys.argv[1]) if len(sys.argv)>1 else 2
    total = int(sys.argv[2]) if len(sys.argv)>2 else 1000
    results = []
    done = 0
    print(f"Farming {total} accounts with {workers} workers...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(farm_one, i, done): i for i in range(total)}
        for fut in concurrent.futures.as_completed(futs):
            try:
                r = fut.result()
                results.append(r)
                done += 1
                if r["status"]=="OK":
                    print(f"[{done}/{total}] ✅ {r['email']} sid={r['sid']} sub={r['sub']}")
                else:
                    print(f"[{done}/{total}] ❌ {r['email']} {r['status']}")
                if done % 10 == 0:
                    json.dump(results, open(os.path.join(BASE,"farm_results.json"),"w"), indent=1)
            except Exception as e:
                done += 1
                print(f"[{done}/{total}] ERR {e}")
    json.dump(results, open(os.path.join(BASE,"farm_results.json"),"w"), indent=1)
    ok = sum(1 for r in results if r["status"]=="OK")
    print(f"\nDONE: {ok}/{len(results)} OK")

if __name__ == "__main__":
    main()
