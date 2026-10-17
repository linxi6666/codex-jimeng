import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from http.server import ThreadingHTTPServer
from draft_executor.service import APIHandler, DraftExecutor, ExecutorError, EXPECTED_SETTINGS, validate_plan


PROJECT = "e7ec7935-b916-4572-b38f-76cb899a0168"
TARGET = "node_0123456789"
ASSET = "node_abcdefghjk"


def make_plan():
    prompt = ("山神-13-1-01\n场景参考：{{node:node_abcdefghjk}}\n"
              "镜头组空间声明：屋内，甲在门侧，摄影机在关系线同侧。\n"
              "镜头01｜0–8秒\n景别：中景\n画面：甲走进屋内。")
    return {"projectId": PROJECT, "projectConfirmed": True, "drama": "山神", "episode": "13",
            "promptSource": {"mode": "model"}, "settings": EXPECTED_SETTINGS.copy(), "generate": False,
            "shots": [{"shot": "1-01", "nodeId": TARGET, "updateId": str(uuid.uuid4()),
                       "title": "山神-13-1-01 入屋", "duration": 8, "prompt": prompt,
                       "refs": [f"node:{ASSET}"]}]}


def saved_node(shot):
    return {"nodeId": shot["nodeId"], "type": "video", "title": shot["title"], "status": "empty",
            "resources": [], "upstreamNodeIds": [ASSET], "generation": {
                "mode": "m2v", "model": "seedance_2.0_mini", "ratio": "9:16", "resolution": "720p",
                "outputCount": 1, "durationSeconds": shot["duration"], "prompt": shot["prompt"],
                "references": [{"kind": "node", "id": ASSET}],
                "promptParts": [{"kind": "text", "text": "场景参考："}, {"kind": "reference", "referenceIndex": 0}]}}


class FakeCLI:
    def __init__(self, initial=None):
        self.nodes = initial or {}
        self.writes = []

    def version(self):
        return {"data": {"version": "test"}}

    def auth_status(self):
        return {"data": {"loggedIn": True}}

    def show(self, project_id, node_ids):
        return ({x: self.nodes[x] for x in node_ids if x in self.nodes}, "request-read")

    def create(self, project_id, shot):
        self.writes.append(("create", project_id, shot["nodeId"], shot["updateId"]))
        self.nodes[shot["nodeId"]] = saved_node(shot)
        return {"meta": {"requestId": "request-save"}}

    def edit(self, project_id, shot):
        self.writes.append(("edit", project_id, shot["nodeId"], shot["updateId"]))
        self.nodes[shot["nodeId"]] = saved_node(shot)
        return {"meta": {"requestId": "request-save"}}


class DraftExecutorTests(unittest.TestCase):
    def test_validates_plan_and_generation_off(self):
        plan = make_plan()
        self.assertTrue(validate_plan(plan)["valid"])
        plan["generate"] = True
        with self.assertRaises(ExecutorError) as ctx:
            validate_plan(plan)
        self.assertEqual(ctx.exception.code, "invalid_plan")

    def test_rejects_prompt_ref_mismatch(self):
        plan = make_plan()
        plan["shots"][0]["refs"] = []
        with self.assertRaises(ExecutorError):
            validate_plan(plan)

    def test_creates_then_reads_back_and_is_idempotent(self):
        plan = make_plan()
        cli = FakeCLI()
        with tempfile.TemporaryDirectory() as tmp:
            executor = DraftExecutor(cli, Path(tmp))
            result = executor.save(plan)
            self.assertTrue(result["ok"])
            self.assertEqual(result["written"], [TARGET])
            self.assertEqual(cli.writes[0][0], "create")
            again = executor.save(plan)
            self.assertEqual(again["written"], [])
            self.assertEqual(len(cli.writes), 1)

    def test_existing_generated_node_is_never_overwritten(self):
        plan = make_plan()
        old = saved_node(plan["shots"][0])
        old["status"] = "success"
        old["resources"] = [{"resourceId": "test-resource"}]
        cli = FakeCLI({TARGET: old})
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ExecutorError) as ctx:
                DraftExecutor(cli, Path(tmp)).save(plan, allow_overwrite=True)
            self.assertEqual(ctx.exception.code, "protected_existing_output")
            self.assertFalse(cli.writes)

    def test_requires_explicit_overwrite_of_existing_draft(self):
        plan = make_plan()
        plan["shots"][0]["prompt"] += "\n只改提示词正文"
        old_plan = make_plan()
        old = saved_node(old_plan["shots"][0])
        cli = FakeCLI({TARGET: old})
        with tempfile.TemporaryDirectory() as tmp:
            executor = DraftExecutor(cli, Path(tmp))
            with self.assertRaises(ExecutorError) as ctx:
                executor.save(plan)
            self.assertEqual(ctx.exception.code, "overwrite_not_authorized")
            result = executor.save(plan, allow_overwrite=True)
            self.assertEqual(result["written"], [TARGET])
            self.assertEqual(cli.writes[-1][0], "edit")

    def test_loopback_api_accepts_local_client_and_rejects_browser_origin(self):
        cli = FakeCLI()
        handler = type("TestHandler", (APIHandler,), {"executor": DraftExecutor(cli, Path(tempfile.gettempdir()))})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/v1/validate"
        payload = json.dumps({"plan": make_plan()}, ensure_ascii=False).encode("utf-8")
        try:
            request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=3) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(json.loads(response.read())["valid"])
            cross_origin = urllib.request.Request(url, data=payload, headers={
                "Content-Type": "application/json", "Origin": "https://evil.example"})
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(cross_origin, timeout=3)
            self.assertEqual(ctx.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
