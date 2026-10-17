"""Optional read-only check against the running manager; no uploads or mutations."""
import http.cookiejar
import json
import sys
import urllib.parse
import urllib.request

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def get(path):
    with client.open(base + path, timeout=90) as response:
        assert response.status == 200
        return response.read()


assert b"/app.js" in get("/")
assert "csrf" in json.loads(get("/api/session"))
status = json.loads(get("/api/status"))
assert status["version"]["version"]
canvases = json.loads(get("/api/canvases"))["items"]
counts = {}
if canvases:
    project = canvases[-1]["projectId"]
    for kind in ("video", "element"):
        data = json.loads(get("/api/nodes?" + urllib.parse.urlencode({"project": project, "type": kind})))
        counts[kind] = len(data["items"])
        if data["items"]:
            node = json.loads(get("/api/node?" + urllib.parse.urlencode({"project": project, "node": data["items"][0]["nodeId"]})))
            assert node["node"]["type"] == kind
assert isinstance(json.loads(get("/api/jobs"))["items"], list)
print(json.dumps({"http": "ok", "version": status["version"]["version"], "loggedIn": status["auth"]["loggedIn"],
                  "canvasCount": len(canvases), "sampleNodeCounts": counts, "writes": 0}, ensure_ascii=False))
