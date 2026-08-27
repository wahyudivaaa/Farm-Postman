import re

html = open(r"D:\Project\Farm Postman\recon\signup.html", encoding="utf-8").read()

# find turnstile render invocation & config details
print("=== RENDER CALL ===")
for m in list(re.finditer(r'turnstile\.render\([^)]{0,300}', html))[:3]:
    print(m.group(0)[:350])
    print('---')

print("\n=== TURNSTILE CONFIG BLOCK ===")
i = html.find('turnstileConfig.siteKey')
print(html[max(0,i-200):i+900])

print("\n=== cData / chlPageData ===")
for kw in ['cData', 'chlPageData', 'retry:', 'refresh-expired', 'appearance']:
    for m in list(re.finditer(re.escape(kw), html))[:2]:
        j = m.start()
        print(f"[{kw}]", html[max(0,j-80):j+150].replace('\n',' ')[:230])
