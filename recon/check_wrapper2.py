import re

html = open(r"D:\Project\Farm Postman\recon\turnstile_wrapper.js", encoding="utf-8").read()
print(len(html))
print("=== FULL WRAPPER ===")
print(html[1400:])
