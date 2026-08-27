import re

for name in ["signup", "login"]:
    html = open(rf"D:\Project\Farm Postman\recon\{name}.html", encoding="utf-8").read()
    print(f"########## {name}.html ##########")
    # find xhr.onreadystatechange / onload handlers
    for m in list(re.finditer(r'xhr\.(?:onreadystatechange|onload)\s*=\s*function[\s\S]{0,1200}', html))[:2]:
        txt = m.group(0)
        print(txt[:1200])
        print('-----')
