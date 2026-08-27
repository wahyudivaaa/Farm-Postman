import re

for name, kw in [("signup", "authFlowId"), ("login", "authFlowId")]:
    html = open(rf"D:\Project\Farm Postman\recon\{name}.html", encoding="utf-8").read()
    print(f"######## {name}.html — authFlowId references ########")
    for m in list(re.finditer(kw, html))[:6]:
        i = m.start()
        print(html[max(0,i-150):i+200].replace('\n', ' ')[:350])
        print('---')