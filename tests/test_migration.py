import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import migrate_haishan as migration
from manager import CLIError, Store
from test_manager import FakeCLI, PNG, PROJECT


class MigrationCLI(FakeCLI):
    def call(self, args, timeout=60):
        result = super().call(args, timeout)
        if args[:2] == ["node", "create"]:
            ident = args[args.index("--node-id") + 1]
            self.nodes[ident]["title"] = args[args.index("--title") + 1]
        return result


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "export"
        for kind, name in [("人设", "张三"), ("场景", "街道"), ("道具", "手表")]:
            directory = self.source / kind / name
            directory.mkdir(parents=True)
            (directory / "01主图.png").write_bytes(PNG)
        (self.source / "人设" / "张三" / "02侧面.png").write_bytes(PNG + b"2")
        self.store = Store(self.root / "state")
        self.cli = MigrationCLI()

    def tearDown(self):
        self.temp.cleanup()

    def groups(self):
        return migration.load_groups("浪子回头", source_dir=self.source)

    def prepared(self):
        return [migration.stage(self.store, group) for group in self.groups()]

    def test_new_naming_rule_and_categories(self):
        self.assertEqual([g["title"] for g in self.groups()], ["浪子回头-人设-张三", "浪子回头-场景-街道", "浪子回头-道具-手表"])
        self.assertEqual(migration.make_title("浪子", "角色", "张三-青年"), "浪子-人设-张三-青年")
        for name in ("../escape", "A/B", "", "A:", "名字."):
            with self.assertRaises(ValueError):
                migration.make_title("浪子", "人设", name)

    def test_multiview_group_and_main_sort(self):
        group = self.groups()[0]
        self.assertEqual(len(group["sources"]), 2)
        self.assertTrue(group["sources"][0].endswith("01主图.png"))

    def test_flat_category_export(self):
        (self.source / "道具" / "钥匙.png").write_bytes(PNG)
        self.assertIn("浪子回头-道具-钥匙", [g["title"] for g in self.groups()])

    def test_unknown_category_and_ungrouped_images_rejected(self):
        bad = self.source / "misc"
        bad.mkdir()
        (bad / "wrong.png").write_bytes(PNG)
        with self.assertRaises(ValueError):
            self.groups()

    def test_preview_never_calls_cli_or_writes_state(self):
        state = self.root / "unused"
        with patch.object(migration, "CLI", side_effect=AssertionError("no remote calls")), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(migration.main(["--source-dir", str(self.source), "--state-dir", str(state)]), 0)
        self.assertFalse(state.exists())

    def test_stage_standard_names_preserve_originals_and_reuse(self):
        group = self.groups()[0]
        first = migration.stage(self.store, group)
        second = migration.stage(self.store, group)
        self.assertEqual(first, second)
        self.assertEqual(self.store.file(first["files"][0])["name"], "浪子回头-人设-张三-01.png")
        self.assertTrue(Path(group["sources"][0]).exists())
        self.assertEqual(Path(self.store.file(first["files"][0])["path"]).read_bytes(), PNG)

    def test_changed_input_and_corrupted_staging_rejected(self):
        group = self.groups()[0]
        migration.stage(self.store, group)
        Path(group["sources"][0]).write_bytes(PNG + b"changed")
        with self.assertRaisesRegex(ValueError, "变化"):
            migration.stage(self.store, group)

    def test_html_download_rejected_without_secret_output(self):
        secret = "https://public.example/image.png?token=PRIVATE"
        group = {"title": "浪子回头-人设-张三", "description": "", "sources": [secret]}
        with patch.object(migration, "public_https"), patch.object(migration, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(b"<html>login</html>")
            with self.assertRaisesRegex(ValueError, "不是支持的图片"):
                migration.stage(self.store, group)
        self.assertFalse(list(self.store.root.rglob("*.part")))

    def test_download_and_receipt_hide_source_url(self):
        source = "https://public.example/image.png?token=PRIVATE"
        group = {"title": "浪子回头-人设-张三", "description": "", "sources": [source]}
        with patch.object(migration, "public_https"), patch.object(migration, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(PNG)
            migration.stage(self.store, group)
            migration.stage(self.store, group)
            self.assertEqual(opener.return_value.open.call_count, 1)
        receipts = list(self.store.root.rglob("receipt.json"))
        self.assertEqual(len(receipts), 1)
        self.assertNotIn("PRIVATE", receipts[0].read_text(encoding="utf-8"))
        self.assertNotIn("https://", receipts[0].read_text(encoding="utf-8"))

    def test_download_size_limit_and_network_failures(self):
        group = {"title": "浪子回头-人设-张三", "description": "", "sources": ["https://public.example/x?token=PRIVATE"]}
        with patch.object(migration, "public_https"), patch.object(migration, "build_opener") as opener, patch.object(migration, "MAX_IMAGE", 10):
            opener.return_value.open.return_value = io.BytesIO(PNG)
            with self.assertRaisesRegex(ValueError, "32MiB"):
                migration.stage(self.store, group)
            opener.return_value.open.side_effect = OSError("https://secret?token=PRIVATE")
            with self.assertRaises(ValueError) as caught:
                migration.stage(self.store, group)
            self.assertNotIn("PRIVATE", str(caught.exception))

    def test_https_only_and_private_addresses_rejected(self):
        for url in ("http://public.example/x", "https://user:password@public.example/x", "https://127.0.0.1/x"):
            with self.assertRaises(ValueError):
                migration.public_https(url)

    def test_csv_manifest_and_relative_local_paths(self):
        path = self.root / "sources.csv"
        path.write_text("kind,name,source,description\n人设,张三,export/人设/张三/01主图.png,青年\n", encoding="utf-8-sig")
        groups = migration.load_groups("浪子", manifest=path)
        self.assertEqual(groups[0]["title"], "浪子-人设-张三")
        self.assertEqual(groups[0]["description"], "青年")

    def test_end_to_end_fake_upload_bindings_and_idempotent_rerun(self):
        groups = self.prepared()
        result = migration.migrate(self.store, self.cli, PROJECT, groups)
        self.assertEqual(len(result), 3)
        calls = len([a for a in self.cli.calls if a[:2] == ["resource", "upload"]])
        self.assertEqual(calls, 4)
        again = migration.migrate(self.store, self.cli, PROJECT, groups)
        self.assertEqual(result, again)
        self.assertEqual(calls, len([a for a in self.cli.calls if a[:2] == ["resource", "upload"]]))
        self.assertFalse(any("--run" in a for a in self.cli.calls))

    def test_lost_upload_response_requires_resume_and_never_reuploads(self):
        groups = self.prepared()[:1]
        self.cli.fail_upload_once = True
        with self.assertRaises(CLIError):
            migration.migrate(self.store, self.cli, PROJECT, groups)
        with self.assertRaisesRegex(ValueError, "--resume"):
            migration.migrate(self.store, self.cli, PROJECT, groups)
        result = migration.migrate(self.store, self.cli, PROJECT, groups, resume=True)
        self.assertEqual(len(result), 1)
        uploads = [a for a in self.cli.calls if a[:2] == ["resource", "upload"]]
        self.assertEqual(len(uploads), 2)  # two different images, no replay

    def test_successful_subject_deleted_stops_instead_of_recreating(self):
        groups = self.prepared()[:1]
        result = migration.migrate(self.store, self.cli, PROJECT, groups)
        del self.cli.nodes[result[0]["nodeId"]]
        writes = len([a for a in self.cli.calls if a[:2] == ["node", "create"]])
        with self.assertRaisesRegex(ValueError, "回读不一致"):
            migration.migrate(self.store, self.cli, PROJECT, groups)
        self.assertEqual(writes, len([a for a in self.cli.calls if a[:2] == ["node", "create"]]))

    def test_changed_same_name_does_not_create_duplicate(self):
        groups = self.prepared()[:1]
        migration.migrate(self.store, self.cli, PROJECT, groups)
        groups[0]["description"] = "新描述"
        with self.assertRaisesRegex(ValueError, "不同迁移内容"):
            migration.migrate(self.store, self.cli, PROJECT, groups)

    def test_execute_without_target_has_no_side_effects(self):
        state = self.root / "unused"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(migration.main(["--source-dir", str(self.source), "--state-dir", str(state), "--execute"]), 1)
        self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
