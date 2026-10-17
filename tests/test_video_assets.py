import http.client
import json
import tempfile
import threading
import unittest

from manager import App, Handler, Store, ThreadingHTTPServer
from test_manager import FakeCLI
from video_assets import DEFAULT_PROJECTS, SOURCE, VideoAssets, classify_prompt, validate_projects
from asset_server import AssetHandler


class VideoAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.assets = VideoAssets(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self, prompts):
        return {"source": SOURCE, "items": [{"prompt": p, "duration": "25s"} for p in prompts]}

    def test_known_prefix_and_alias(self):
        projects = validate_projects([{"name": "浪子回头", "aliases": ["浪子"]}])
        for prompt in ("浪子回头-第1集", "浪子：第2集", "【浪子】对白", "[浪子回头]动作", "\ufeff  浪子回头\n镜头"):
            self.assertEqual(classify_prompt(prompt, projects)[0], "浪子回头")

    def test_explicit_book_title_autodiscovers_project(self):
        self.assertEqual(classify_prompt("《新剧》-第2集", [])[0], "新剧")
        self.assertEqual(classify_prompt("剧名：新剧\n镜头一", [])[0], "新剧")
        self.assertEqual(classify_prompt("项目: 新剧\n镜头二", [])[0], "新剧")

    def test_only_start_never_guess_from_body_or_characters(self):
        for prompt in ("", "水生是水生；瑞英是瑞英", "电影感，参考《浪子回头》", "画面描写\n浪子回头-第1集", "浪子回头了，拥抱家人", "未知剧-第1集", "【电影感】画面"):
            self.assertEqual(classify_prompt(prompt, DEFAULT_PROJECTS)[0], "其他")

    def test_longest_prefix_with_separator(self):
        projects = validate_projects([{"name": "浪子", "aliases": []}, {"name": "浪子回头", "aliases": []}])
        self.assertEqual(classify_prompt("浪子回头-镜头1", projects)[0], "浪子回头")
        self.assertEqual(classify_prompt("浪子回头是个故事", projects)[0], "其他")

    def test_registration_reclassifies_existing_records(self):
        self.assets.import_snapshot(self.snapshot(["乡土-第1集", "无标题视频"]))
        self.assertEqual(self.assets.listing(project="其他")["total"], 2)
        self.assets.set_projects([{"name": "乡土剧", "aliases": ["乡土"]}])
        self.assertEqual(self.assets.listing(project="乡土剧")["total"], 1)
        self.assertEqual(self.assets.listing(project="其他")["total"], 1)

    def test_config_is_durable(self):
        self.assets.set_projects([{"name": "乡土", "aliases": []}])
        self.assertEqual(VideoAssets(self.store).projects()[0]["name"], "乡土")

    def test_alias_collisions_and_reserved_names_rejected(self):
        for projects in ([{"name": "其他"}], [{"name": "A", "aliases": ["a"]}],
                         [{"name": "A", "aliases": ["B"]}, {"name": "B"}], [{"name": "X\nY"}]):
            with self.assertRaises(ValueError):
                validate_projects(projects)

    def test_same_snapshot_dedup_but_identical_prompt_outputs_preserved(self):
        data = self.snapshot(["《浪子回头》镜头", "《浪子回头》镜头"])
        self.assertEqual(self.assets.import_snapshot(data)["added"], 2)
        self.assertEqual(self.assets.import_snapshot(data)["updated"], 2)
        self.assertEqual(self.assets.listing()["total"], 2)

    def test_export_roundtrip_preserves_local_record_identity(self):
        self.assets.import_snapshot(self.snapshot(["浪子回头-镜头", "未知视频"]))
        data = self.assets.export()
        data["items"][0]["prompt"] = "《改名剧》-镜头1"
        self.assertEqual(self.assets.import_snapshot(data)["updated"], 2)
        self.assertEqual(self.assets.listing()["total"], 2)

    def test_filter_counts_pagination(self):
        self.assets.import_snapshot(self.snapshot([f"《浪子回头》镜头{i}" for i in range(55)] + ["未知视频"]))
        first = self.assets.listing(project="浪子回头", limit=50)
        self.assertEqual(first["total"], 55)
        self.assertTrue(first["hasMore"])
        self.assertEqual(len(self.assets.listing(project="浪子回头", offset=50)["items"]), 5)
        self.assertEqual(self.assets.listing(search="未知")["total"], 1)
        self.assertEqual(self.assets.listing(project="其他")["indexedTotal"], 56)

    def test_canvas_and_private_fields_rejected_atomically(self):
        data = self.snapshot(["《剧名》镜头", "bad"])
        data["items"][1]["url"] = "https://signed?token=secret"
        with self.assertRaises(ValueError):
            self.assets.import_snapshot(data)
        self.assertEqual(self.assets.listing()["total"], 0)
        with self.assertRaises(ValueError):
            self.assets.import_snapshot({"source": "canvas", "items": [{"prompt": "foo"}]})

    def test_urls_in_visible_prompt_not_persisted(self):
        self.assets.import_snapshot(self.snapshot(["《剧名》 https://signed?token=PRIVATE 画面"]))
        self.assertNotIn("PRIVATE", json.dumps(self.assets.export()))

    def test_duplicate_ids_rejected(self):
        self.assets.import_snapshot(self.snapshot(["视频"]))
        data = self.assets.export()
        data["items"].append(data["items"][0].copy())
        with self.assertRaises(ValueError):
            self.assets.import_snapshot(data)


class AssetHTTPTests(unittest.TestCase):
    handler = Handler
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = App(Store(self.temp.name), FakeCLI())
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        self.server.daemon_threads = True
        self.server.app = self.app
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.headers = {}
        _, headers, _ = self.request("/")
        self.headers = {"Cookie": headers["Set-Cookie"].split(";", 1)[0]}
        _, _, data = self.request("/api/session")
        self.headers.update({"X-CSRF-Token": json.loads(data)["csrf"], "Content-Type": "application/json",
                             "Origin": f"http://127.0.0.1:{self.server.server_port}"})

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, data=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        conn.request("GET" if data is None else "POST", path, json.dumps(data) if data is not None else None,
                     self.headers if headers is None else headers)
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def test_independent_asset_import_filter_and_export(self):
        data = {"source": SOURCE, "items": [{"prompt": "《浪子回头》第1集"}, {"prompt": "无剧名"}]}
        self.assertEqual(self.request("/api/assets/import", data)[0], 200)
        status, _, raw = self.request("/api/assets")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["indexedTotal"], 2)
        self.assertEqual(self.request("/api/assets/export")[0], 200)
        self.assertEqual(self.app.cli.calls, [], "asset catalogue must never substitute canvas commands")

    def test_local_routes_still_require_session_csrf(self):
        self.assertEqual(self.request("/api/assets", headers={})[0], 403)
        headers = {**self.headers, "X-CSRF-Token": "wrong"}
        self.assertEqual(self.request("/api/assets/projects", {"projects": []}, headers)[0], 403)

    def test_bad_pagination_and_private_payload_return_400(self):
        self.assertEqual(self.request("/api/assets?offset=-1")[0], 400)
        self.assertEqual(self.request("/api/assets/import", {"source": SOURCE, "items": [{"token": "secret"}]})[0], 400)


class StandaloneAssetHTTPTests(AssetHTTPTests):
    handler = AssetHandler

    def test_preview_csp_only_allows_observed_media_hosts(self):
        _, headers, _ = self.request('/')
        policy = headers['Content-Security-Policy']
        self.assertIn("media-src 'self' blob: https://v3-artist.vlabvod.com https://v26-artist.vlabvod.com;", policy)
        self.assertNotIn('https:;', policy)
        self.assertNotIn('*', policy)

    def test_asset_only_session_mode_and_no_cli_operations(self):
        _, _, raw = self.request('/api/session')
        self.assertEqual(json.loads(raw)['mode'], 'video-assets-only')
        self.assertEqual(self.request('/api/canvases')[0], 404)
        self.assertEqual(self.request('/api/download', {'resource': 'anything'})[0], 400)
        self.assertEqual(self.request('/api/subjects', {})[0], 400)
        self.assertEqual(self.app.cli.calls, [])


if __name__ == "__main__":
    unittest.main()
