"""Part 1: CloakBrowser-only auth -> dump fresh cookies to fresh_cookies.json. NO curl_cffi import."""
import asyncio, cloakbrowser, json, sys, random, subprocess, re, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/captcha-solver")
from common.browser import browser_kwargs

EMAIL, USERNAME, PASSWORD = sys.argv[1], sys.argv[2], sys.argv[3]
MAIL_API = os.environ.get("MAIL_API", "https://mail.flashdev.org/api/public/v1")
MAIL_KEY = os.environ.get("MAIL_API_KEY", "CHANGE_ME_cmf_v1_your_flashmail_key_here")

async def click_turnstile(page):
    for _ in range(45):
        fr=[f for f in page.frames if "challenges.cloudflare.com" in (f.url or "")]
        if fr:
            try:
                el=await fr[0].frame_element(); box=await el.bounding_box()
                if box and box.get("width",0)>20:
                    await page.mouse.click(box["x"]+box["width"]/2, box["y"]+box["height"]/2); return True
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
            m=re.search(r'(\d{5,6})', e.get('subject') or '')
            if m: return m.group(1)
    except: pass
    return None

TOKEN_JS="""() => { const sels=['[name=cf-turnstile-response]','#cf-response'];
  for(const s of sels){const e=document.querySelector(s); if(e&&e.value&&e.value.length>20) return e.value;}
  if(window.turnstileConfig&&window.turnstileConfig.token) return window.turnstileConfig.token; return ''; }"""

async def main():
    async with await cloakbrowser.launch_async(**browser_kwargs("TURNSTILE")) as browser:
        page=await browser.new_page()
        try:
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
            await page.click("#sign-up-btn", timeout=15000); await asyncio.sleep(9)
            code=None
            for _ in range(25):
                code=get_code()
                if code: break
                await asyncio.sleep(4)
            for a in range(4):
                if "verify-account" not in page.url: break
                await asyncio.sleep(2)
                try: await page.locator("#verification-code").first.fill(code, timeout=6000)
                except:
                    await page.goto(page.url, wait_until="domcontentloaded", timeout=30000); await asyncio.sleep(2)
                    try: await page.locator("#verification-code").first.fill(code, timeout=6000)
                    except: pass
                await click_turnstile(page)
                for _ in range(20):
                    vtok=await page.evaluate(TOKEN_JS)
                    if len(vtok)>20: break
                    await asyncio.sleep(1)
                try: await page.click('button[type="submit"]', timeout=6000)
                except: pass
                await asyncio.sleep(7)
            try:
                await page.goto("https://go.postman.co/dashboard", wait_until="domcontentloaded", timeout=45000); await asyncio.sleep(6)
            except Exception as e: print("nav:",str(e)[:40])
            await asyncio.sleep(5)
            cookies=await page.context.cookies()
            cmap={c["name"]:c["value"] for c in cookies}
            json.dump(cmap, open(r"D:\Project\Farm Postman\fresh_cookies.json","w"))
            print("[dashboard]", page.url[:80])
            print("cookies:", len(cmap), "| iam:", cmap.get("postman.iam.sid","")[:20])
        finally:
            try: await browser.close()
            except: pass

asyncio.run(main())