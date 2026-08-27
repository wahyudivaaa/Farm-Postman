import re

html = open(r"D:\Project\Farm Postman\recon\signup.html", encoding="utf-8").read()

print("=== GITHUB & GOOGLE OAUTH LINKS ===")
for m in re.finditer(r'(?:github|google)[^>]*href="([^"]+)"', html):
    print("LINK:", m.group(1))

print("\n=== OAUTH / AUTH REDIRECTS ===")
for m in re.finditer(r'"(\/(?:auth|oauth|authorize)[^"]*)"', html):
    print(m.group(1))

print("\n=== github-sign-up / google-sign-up contexts ===")
for cls in ["github-sign-up", "google-sign-up"]:
    i = html.find(cls)
    if i >= 0:
        print(f"[{cls}]", html[max(0,i-300):i+100].replace("\n", " ")[:400])
        print('---')

print("\n=== auth endpoints in scripts ===")
for m in set(re.findall(r'(/api/[a-zA-Z0-9/_-]*(?:oauth|auth|github|google)[a-zA-Z0-9/_-]*)', html)):
    print(m)
for m in set(re.findall(r'(auth\.postman\.com[a-zA-Z0-9/_.-]+)', html)):
    print(m)