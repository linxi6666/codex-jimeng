import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from manager import (App, CLI, CLIError, Handler, StateLock, Store, ThreadingHTTPServer,
                     Worker, media_mime, new_id, node_id, valid_node, validate_schema)

PROJECT = "c5f9eb0d-99a0-4cc7-817b-c57d33c9590e"
PNG = b"\x89PNG\r\n\x1a\n" + b"sample" * 30


class FakeCLI:
    def __init__(self):
        self.calls, self.resources, self.nodes = [], {}, {}
        self.fail_upload_once = False
        self.fail_image_once = False
        self.logged_in = True
        self.fail_query = False
        self.corrupt_binding = False
        self.download_data = b"\x00\x00\x00\x20ftypisom" + b"sample" * 50
        self.corrupt_hash = False

    def call(self, args, timeout=60):
        self.calls.append(list(args))
        def flag(name):
            return args[args.index(name) + 1]
        if args[:2] == ["auth", "status"]:
            return {"loggedIn": self.logged_in}
        if args[:1] == ["version"]:
            return {"version": "test"}
        if args[:2] == ["auth", "account"]:
            return {"isVip": False}
        if args[:2] == ["resource", "upload"]:
            ident = flag("--resource-id")
            self.resources[ident] = {"resourceId": ident, "type": "image", "status": "success"}
            if self.fail_upload_once:
                self.fail_upload_once = False
                raise CLIError("lost upload response", uncertain=True)
            return {"resourceId": ident, "mediaType": "image"}
        if args[:2] == ["resource", "get"]:
            if self.fail_query or args[2] not in self.resources:
                raise CLIError("Cannot determine original resource", action="inspect", uncertain=True)
            return self.resources[args[2]]
        if args[:2] == ["node", "show"]:
            ident = flag("--node-id")
            n = self.nodes.get(ident)
            return {"nodes": [{"nodeId": ident, "result": "FOUND" if n else "NOT_FOUND", **({"node": n} if n else {})}]}
        if args[:3] == ["node", "create", "image"]:
            ident, resource = flag("--node-id"), flag("--resource-id")
            self.nodes[ident] = {"nodeId": ident, "type": "image", "resources": [self.resources[resource]]}
            if self.fail_image_once:
                self.fail_image_once = False
                raise CLIError("lost node response", uncertain=True)
            return {"node": self.nodes[ident]}
        if args[:3] == ["node", "create", "element"]:
            ident = flag("--node-id")
            main = "node_0000000000" if self.corrupt_binding else flag("--main")
            aux = [{"id": args[i+1]} for i, a in enumerate(args) if a == "--auxiliary"]
            self.nodes[ident] = {"nodeId": ident, "type": "element", "subjectBindings": {"main": {"id": main}, "auxiliaries": aux}}
            return {"node": self.nodes[ident]}
        if args[:2] == ["resource", "download"]:
            path = Path(flag("--output")) / "测试视频.mp4"
            path.write_bytes(self.download_data)
            return {"path": str(path), "size": len(self.download_data),
                    "sha256": "bad" if self.corrupt_hash else hashlib.sha256(self.download_data).hexdigest()}
        raise AssertionError("Unexpected command " + repr(args))


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.cli = FakeCLI()
        self.worker = Worker(self.store, self.cli)

    def tearDown(self):
        self.tmp.cleanup()

    def add_file(self, name="主图.png", body=PNG):
        ident = new_id()
        path = self.store.root / "uploads" / (ident + ".png")
        path.write_bytes(body)
        with self.store.connect() as db:
            db.execute("INSERT INTO files VALUES(?,?,?,?,?,?,?,?)", (ident, name, name, str(path),
                       len(body), hashlib.sha256(body).hexdigest(), "image/png", 1))
        return ident

    def create(self, two=False):
        files = [self.add_file()]
        if two:
            files.append(self.add_file("辅助.png", PNG + b"2"))
        batch = new_id()
        groups = [{"title": "商品A", "files": files, "description": "同一个商品"}]
        ids = self.store.add_subjects(PROJECT, groups, batch)
        return ids[0], groups, batch

    def upload_count(self):
        return sum(c[:2] == ["resource", "upload"] for c in self.cli.calls)

    def test_complete_subject_and_auxiliary(self):
        ident, _, _ = self.create(two=True)
        self.worker.process(self.store.claim())
        job = self.store.job(ident)
        self.assertEqual(job["status"], "success")
        self.assertTrue(job["payload"]["done"])
        self.assertEqual(self.upload_count(), 2)
        for args in self.cli.calls:
            self.assertNotIn("--run", args)
            if args[0] not in {"auth", "version", "schema"}:
                self.assertIn("--project-id", args)
        self.assertIsNone(self.store.claim())

    def test_double_submission_same_batch_and_content_dedup(self):
        ident, groups, batch = self.create()
        self.assertEqual(self.store.add_subjects(PROJECT, groups, batch), [ident])
        # Same content copied to a different staged filename is also deduplicated.
        groups[0]["files"] = [self.add_file("copy.png")]
        self.assertEqual(self.store.add_subjects(PROJECT, groups, new_id()), [ident])
        groups[0]["title"] = "商品B"
        with self.assertRaises(ValueError):
            self.store.add_subjects(PROJECT, groups, batch)

    def test_lost_upload_response_queries_original_no_reupload(self):
        ident, _, _ = self.create()
        self.cli.fail_upload_once = True
        self.worker.process(self.store.claim())
        before = self.store.job(ident)
        self.assertEqual(before["status"], "paused")
        self.store.resume(ident)
        self.worker.process(self.store.claim())
        after = self.store.job(ident)
        self.assertEqual(after["status"], "success")
        self.assertEqual(self.upload_count(), 1)
        self.assertEqual(before["payload"]["assets"][0]["resourceId"], after["payload"]["assets"][0]["resourceId"])

    def test_unknown_resource_stays_paused(self):
        ident, _, _ = self.create()
        self.cli.fail_upload_once = True
        self.worker.process(self.store.claim())
        self.cli.fail_query = True
        self.store.resume(ident)
        self.worker.process(self.store.claim())
        self.assertEqual(self.store.job(ident)["status"], "paused")
        self.assertEqual(self.upload_count(), 1)

    def test_lost_node_save_response_reads_node_no_new_save(self):
        ident, _, _ = self.create()
        self.cli.fail_image_once = True
        self.worker.process(self.store.claim())
        self.assertEqual(self.store.job(ident)["status"], "paused")
        self.store.resume(ident)
        self.worker.process(self.store.claim())
        self.assertEqual(self.store.job(ident)["status"], "success")
        self.assertEqual(sum(c[:3] == ["node", "create", "image"] for c in self.cli.calls), 1)

    def test_incomplete_binding_not_success(self):
        ident, _, _ = self.create()
        self.cli.corrupt_binding = True
        self.worker.process(self.store.claim())
        self.assertEqual(self.store.job(ident)["status"], "paused")

    def test_not_logged_in_no_writes(self):
        ident, _, _ = self.create()
        self.cli.logged_in = False
        self.worker.process(self.store.claim())
        self.assertEqual(self.store.job(ident)["status"], "paused")
        self.assertEqual(self.upload_count(), 0)

    def test_restart_running_jobs_become_paused(self):
        ident, _, _ = self.create()
        job = self.store.claim()
        resource = job["payload"]["assets"][0]["resourceId"]
        self.store.recover()
        restarted = self.store.job(ident)
        self.assertEqual(restarted["status"], "paused")
        self.assertEqual(restarted["payload"]["assets"][0]["resourceId"], resource)

    def test_restart_does_not_automatically_upload_queued_jobs(self):
        ident, _, _ = self.create()
        self.store.recover()
        self.assertEqual(self.store.job(ident)["status"], "paused")
        self.assertIsNone(self.store.claim())

    def test_success_cannot_resume(self):
        ident, _, _ = self.create()
        self.worker.process(self.store.claim())
        with self.assertRaises(ValueError):
            self.store.resume(ident)

    def test_pause_does_not_cancel_running_and_reuses_identity(self):
        ident, _, _ = self.create()
        original = self.store.job(ident)["payload"]
        self.assertEqual(self.store.pause_queued(ident), 1)
        self.assertIsNone(self.store.claim())
        self.store.resume(ident)
        job = self.store.claim()
        self.assertEqual(job["payload"], original)
        self.assertEqual(self.store.pause_queued(), 0)
        self.assertEqual(self.store.job(ident)["status"], "running")

    def test_download_hash_verified_and_deduplicated(self):
        resource = new_id()
        self.cli.resources[resource] = {"resourceId": resource, "type": "video", "status": "success"}
        ident = self.store.add_download(PROJECT, resource, "video")
        self.assertEqual(self.store.add_download(PROJECT, resource, "video"), ident)
        self.worker.process(self.store.claim())
        job = self.store.job(ident)
        self.assertEqual(job["status"], "success")
        self.assertTrue(Path(job["payload"]["path"]).is_file())
        self.assertEqual(job["payload"]["mime"], "video/mp4")

    def test_bad_download_hash_not_success(self):
        resource = new_id()
        self.cli.resources[resource] = {"resourceId": resource, "type": "video", "status": "success"}
        ident = self.store.add_download(PROJECT, resource, "video")
        self.cli.corrupt_hash = True
        self.worker.process(self.store.claim())
        self.assertEqual(self.store.job(ident)["status"], "paused")

    def test_node_ids_follow_cli_contract(self):
        for _ in range(100):
            self.assertEqual(valid_node(node_id())[:5], "node_")

    def test_same_directory_single_instance(self):
        lock = StateLock(self.tmp.name)
        try:
            with self.assertRaises(RuntimeError):
                StateLock(self.tmp.name)
        finally:
            lock.close()

    def test_schema_missing_command_rejected(self):
        with self.assertRaises(RuntimeError):
            validate_schema({"schemaVersion": "1", "subcommands": []})

    def test_cli_no_shell_no_generation(self):
        cli = CLI("test.exe")
        for args in (["node", "run"], ["node", "create", "image", "--run"],
                     ["node", "create", "image", "--run=true"], ["version", "--yes"]):
            with self.assertRaises(ValueError):
                cli.call(args)
        with patch("manager.subprocess.run") as run:
            run.return_value.stdout = '{"ok":true,"data":{"version":"test"}}'
            run.return_value.returncode = 0
            self.assertEqual(cli.call(["version"])["version"], "test")
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertIsInstance(run.call_args.args[0], list)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.app = App(self.store, FakeCLI())
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.server.app = self.app
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = ""
        self.csrf = ""

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, path, method="GET", body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        conn.request(method, path, body, headers or {})
        response = conn.getresponse()
        data = response.read()
        result = response.status, dict(response.getheaders()), data
        conn.close()
        return result

    def session(self):
        status, headers, _ = self.request("/")
        self.assertEqual(status, 200)
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        status, _, data = self.request("/api/session", headers={"Cookie": self.cookie})
        self.csrf = json.loads(data)["csrf"]

    def mutation_headers(self, mime="application/json"):
        return {"Cookie": self.cookie, "X-CSRF-Token": self.csrf,
                "Origin": f"http://127.0.0.1:{self.server.server_port}", "Content-Type": mime}

    def test_session_required_and_static_csp(self):
        self.assertEqual(self.request("/api/jobs")[0], 403)
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertIn(b"/app.js", body)
        self.assertEqual(self.request("/", headers={"Host": "evil.example"})[0], 403)

    def test_cross_site_and_csrf_rejected(self):
        self.session()
        headers = self.mutation_headers()
        headers["Origin"] = "http://evil.example"
        self.assertEqual(self.request("/api/login", "POST", "{}", headers)[0], 403)
        headers = self.mutation_headers()
        headers["X-CSRF-Token"] = "wrong"
        self.assertEqual(self.request("/api/login", "POST", "{}", headers)[0], 403)

    def test_upload_binary_signature_and_traversal_safe(self):
        self.session()
        headers = self.mutation_headers("application/octet-stream")
        status, _, body = self.request("/api/upload?name=../../outside.png", "POST", PNG, headers)
        self.assertEqual(status, 200)
        record = self.store.file(json.loads(body)["id"])
        self.assertTrue(Path(record["path"]).is_relative_to(self.store.root / "uploads"))
        status, _, _ = self.request("/api/upload?name=evil.png", "POST", b"<script>bad</script>", headers)
        self.assertEqual(status, 400)
        self.assertEqual(list((self.store.root / "uploads").glob("*.part")), [])

    def test_no_arbitrary_command_route(self):
        self.session()
        self.assertEqual(self.request("/api/exec", "POST", '{"command":"whoami"}', self.mutation_headers())[0], 404)

    def test_media_ranges_and_download(self):
        self.session()
        resource = new_id()
        self.app.cli.resources[resource] = {"resourceId": resource, "type": "video", "status": "success"}
        ident = self.store.add_download(PROJECT, resource, "video")
        self.app.worker.process(self.store.claim())
        status, headers, data = self.request("/media/" + ident, headers={"Cookie": self.cookie, "Range": "bytes=2-8"})
        self.assertEqual(status, 206)
        self.assertEqual(data, self.app.cli.download_data[2:9])
        self.assertTrue(headers["Content-Range"].startswith("bytes 2-8/"))
        self.assertEqual(self.request("/media/" + ident, headers={"Cookie": self.cookie, "Range": "bytes=99999-"})[0], 416)
        status, headers, _ = self.request("/media/" + ident + "?download=1", headers={"Cookie": self.cookie})
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])


if __name__ == "__main__":
    unittest.main()
