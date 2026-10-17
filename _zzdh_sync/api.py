import json, urllib.request, sys

API = "http://127.0.0.1:8766/v1/tools/call"

def call(name, arguments=None, timeout=60):
    body = json.dumps({"name": name, "arguments": arguments or {}}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8")
    try:
        return json.loads(raw)
    except Exception:
        return {"_raw": raw}

def emit(obj, path=None):
    s = json.dumps(obj, ensure_ascii=False, indent=2)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(s)
    return s

if __name__ == "__main__":
    out = call(sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 else {})
    p = sys.argv[3] if len(sys.argv) > 3 else None
    s = emit(out, p)
    if not p:
        print(s)
