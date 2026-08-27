"""
Postman Desktop CDP driver — attach to the running app via remote debugging and inspect/inject.

Launch Postman with:
    Postman.exe --remote-debugging-port=9225 --remote-allow-origins=* --user-data-dir="<temp>"
Then connect (use suppress_origin=True — websocket-client sends an Origin header otherwise and CDP rejects it).

Usage:
    python postman_cdp.py <ws_url> '<js expression>'
"""
import json, websocket, sys, time

def attach(url, timeout=30):
    ws = websocket.create_connection(url, timeout=timeout, suppress_origin=True)
    mid = [0]
    def send(method, params=None):
        mid[0] += 1
        ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == mid[0]:
                return msg
    def ev(expr):
        r = send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        return r.get("result", {}).get("result", {}).get("value")
    send("Runtime.enable")
    send("Network.enable")
    return ws, send, ev

if __name__ == "__main__":
    url, expr = sys.argv[1], sys.argv[2]
    ws, send, ev = attach(url)
    print(ev(expr))
    ws.close()