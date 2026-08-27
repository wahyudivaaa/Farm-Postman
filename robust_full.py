"""
ROBUST all-in-one: signup -> token-wait -> submit -> poll code -> fill -> turnstile verify
             -> RETRY verify until past verify-account -> onboarding -> capture FULL session.
"""
import asyncio, cloakbrowser, json, sys, random, subprocess, re, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/captcha-solver")
from common.browser import browser_kwargs

EMAIL, USERNAME, PASSWORD = sys.argv[1], sys.argv[2], sys.argv[3]
OUT_PATH = os.environ.get("FARM_OUT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "robust_result.json")
MAIL_API = os.environ.get("MAIL_API", "https://mail.flashdev.org/api/public/v1")
MAIL_KEY = os.environ.get("MAIL_API_KEY", "CHANGE_ME_cmf_v1_your_flashmail_key_here")

async def click_turnstile(page):
    for _ in range(45):
        fr=[f for f in page.frames if "challenges.cloudflare.com" in (f.url or "")]
        if fr:
            try:
                el=await fr[0].frame_element(); box=await el.bounding_box()
                if box and box.get("width",0)>20:
                    x=box["x"]+box["width"]/2+random.randint(-6,6); y=box["y"]+box["height"]/2
                    await page.mouse.move(x,y,steps=8); await asyncio.sleep(0.3)
                    await page.mouse.click(x,y); return True
            except: pass
        await asyncio.sleep(1)
    return False

def get_code():
    cmd=["curl","-s",f"{MAIL_API}/user_mailbox?username={USERNAME}&domain=devflash.online",
         "-H",f"Authorization: Bearer {MAIL_KEY}","--max-time","25"]
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=35)
    try:
        j=json.loads(r.stdout)
        for e in j.get('data',{}).get('emails',[]):
            subj=e.get('subject') or ''
            m=re.search(r'(\d{5,6})', subj)
            if m: return m.group(1)
    except: pass
    return None

TOKEN_JS="""() => { const sels=['[name=cf-turnstile-response]','#cf-response'];
  for(const s of sels){const e=document.querySelector(s); if(e&&e.value&&e.value.length>20) return e.value;}
  if(window.turnstileConfig&&window.turnstileConfig.token) return window.turnstileConfig.token; return ''; }"""

async def main():
    async with await cloakbrowser.launch_async(**browser_kwargs("TURNSTILE")) as browser:
        page=await browser.new_page()
        out={"status":"incomplete","url":"","pm":{}}
        try:
            # signup
            await page.goto("https://identity.getpostman.com/signup", wait_until="domcontentloaded", timeout=45000)
            try: await page.wait_for_load_state("networkidle", timeout=15000)
            except: pass
            await asyncio.sleep(2)
            await page.fill("#email",EMAIL); await page.fill("#username",USERNAME); await page.fill("#password",PASSWORD)
            await asyncio.sleep(1.5); await click_turnstile(page)
            tok=""
            for _ in range(35):
                tok=await page.evaluate(TOKEN_JS)
                if len(tok)>20: break
                await asyncio.sleep(1)
            if len(tok)<=20:
                out["status"]="no_signup_token"; json.dump(out,open(OUT_PATH,"w")); return
            await page.click("#sign-up-btn", timeout=15000); await asyncio.sleep(9)

            # poll code with retry
            code=None
            for _ in range(25):
                code=get_code()
                if code: break
                await asyncio.sleep(4)

            # verify step with RETRY (up to 10 attempts — verify-account Turnstile is flaky)
            verified=False
            for attempt in range(10):
                if "verify-account" not in page.url:
                    verified=True; break
                cur=page.url
                # re-poll code (it may have just arrived)
                if code is None:
                    for _ in range(20):
                        code=get_code()
                        if code: break
                        await asyncio.sleep(3)
                await asyncio.sleep(2)
                try:
                    await page.locator("#verification-code").first.fill(code or "000000", timeout=6000)
                except Exception:
                    await page.goto(cur, wait_until="domcontentloaded", timeout=45000); await asyncio.sleep(2)
                    try: await page.locator("#verification-code").first.fill(code or "000000", timeout=6000)
                    except: pass
                # ensure turnstile solved
                await click_turnstile(page)
                for _ in range(25):
                    vtok=await page.evaluate(TOKEN_JS)
                    if len(vtok)>20: break
                    await asyncio.sleep(1)
                # try submit via button AND Enter fallback
                try: await page.click('button[type="submit"]', timeout=6000)
                except: pass
                try:
                    await page.keyboard.press("Enter")
                except: pass
                await asyncio.sleep(8)
                if "verify-account" not in page.url:
                    verified=True; break
                # if stuck after many attempts, reload page to reset turnstile state
                if attempt in (3, 6):
                    try: await page.reload(wait_until="domcontentloaded", timeout=30000)
                    except: pass
                    await asyncio.sleep(3)
            out["verify"]=verified
            print("[verify] passed:", verified, "url:", page.url[:120])

            # onboarding
            if "onboarding" in page.url or verified:
                await asyncio.sleep(3)
                for step in range(6):
                    for b in ["button:has-text('Continue')","button:has-text('Next')","button:has-text('Done')","button:has-text('Get Started')","button:has-text('Create')","button:has-text('Skip')"]:
                        try:
                            el=page.locator(b).first
                            if await el.count() and await el.is_visible():
                                await el.click(timeout=5000); await asyncio.sleep(2); break
                        except: pass
                    for inp in ['input[name="workspace"]','input[placeholder*="workspace"]','input#workspace-name','input[name="firstName"]','input[name="role"]']:
                        try:
                            el=page.locator(inp).first
                            if await el.count() and await el.is_visible():
                                await el.fill(username if "workspace" in (inp or "") else "Wahyu", timeout=5000); await asyncio.sleep(1); break
                        except: pass
                    await asyncio.sleep(3)
                    if "onboarding" not in page.url:
                        break
            out["url"]=page.url
            print("[final] url:", page.url[:180])

            # capture session
            cookies=await page.context.cookies()
            pm={}
            for c in cookies:
                d=c.get("domain","")
                if any(x in d for x in ["postman.co","getpostman.com","postman.com"]):
                    pm[c["name"]]=c["value"]
            out["pm"]=pm
            out["status"]="verified_authed" if ("postman.iam.sid" in pm or "postman.sid" in pm and "onboarding" not in page.url) else "need_check"
            json.dump(out, open(OUT_PATH,"w"), indent=1)
            print("session keys:", list(pm.keys())[:15])
            print("STATUS:", out["status"])
        except Exception as e:
            out["error"]=str(e); json.dump(out,open(OUT_PATH,"w"))
            print("ERR:", str(e)[:200])
        finally:
            try: await browser.close()
            except: pass

asyncio.run(main())