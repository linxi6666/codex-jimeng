"""Local Dreamina manager. Standard library only; never invokes generation."""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from video_assets import VideoAssets

ROOT = Path(__file__).resolve().parent
ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_IMAGE = 32 * 1024 * 1024  # App limit, not a claimed service limit.


def new_id():
    return str(uuid.uuid4())


def node_id():
    return "node_" + "".join(secrets.choice(ALPHABET) for _ in range(10))


def valid_uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("标识必须是小写标准 UUID")
    return value


def valid_node(value):
    if not isinstance(value, str) or not re.fullmatch(r"node_[0-9abcdefghjkmnpqrstvwxyz]{10}", value):
        raise ValueError("节点标识格式错误")
    return value


def text(value, limit=300):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError(f"文本不能为空，且不能超过 {limit} 字")
    return value.strip()


def media_mime(head, suffix=""):
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp":
        return "video/mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    return mimetypes.guess_type("file" + suffix)[0] or "application/octet-stream"


class CLIError(Exception):
    def __init__(self, message, code=None, action=None, request_id=None, uncertain=False):
        super().__init__(message)
        self.info = {"message": message, "exitCode": code, "requiredAction": action,
                     "requestId": request_id, "uncertain": uncertain}


class CLI:
    # No shell, no arbitrary command endpoint, no generation flags or commands.
    ALLOWED = {("version",), ("schema",), ("auth", "status"), ("auth", "account"),
               ("auth", "login"), ("auth", "wait"), ("canvas", "ls"),
               ("node", "find"), ("node", "show"), ("node", "create", "image"),
               ("node", "create", "element"), ("resource", "upload"),
               ("resource", "get"), ("resource", "download")}

    def __init__(self, executable):
        self.executable = str(executable)

    def call(self, args, timeout=60):
        if not any(tuple(args[:len(prefix)]) == prefix for prefix in self.ALLOWED):
            raise ValueError("不支持的 CLI 操作")
        if any(a.split("=", 1)[0] in {"--run", "--yes", "--credit-token", "--credit-ceiling"} for a in args):
            raise ValueError("管理台不允许生成或批准积分")
        try:
            result = subprocess.run(
                [self.executable, "--format", "json", "--non-interactive", *args],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise CLIError("命令等待超时，结果不确定；请核对后恢复原任务", action="resume", uncertain=True)
        except OSError:
            raise CLIError("无法启动 CLI，请检查安装位置", action="check_installation")
        try:
            payload = json.loads(result.stdout)
        except (ValueError, TypeError):
            # Do not expose raw output: it might contain credentials or signed URLs.
            raise CLIError("CLI 未返回有效 JSON；没有自动重试", code=result.returncode,
                           action="inspect", uncertain=True)
        if not isinstance(payload, dict):
            raise CLIError("CLI 返回格式不兼容", action="inspect", uncertain=True)
        if result.returncode or not payload.get("ok"):
            error = payload.get("error") or {}
            message = error.get("message", "CLI 操作未完成")
            message = re.sub(r"https?://\S+", "[链接已隐藏]", message)[:1500]
            raise CLIError(message, result.returncode, error.get("requiredAction"),
                           (payload.get("meta") or {}).get("requestId"),
                           error.get("class") in {"operation_incomplete", "transport"})
        return payload.get("data") or {}


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class Store:
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for folder in ("uploads", "downloads"):
            (self.root / folder).mkdir(exist_ok=True)
        self.path = self.root / "manager.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS files (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL, relative_name TEXT NOT NULL,
                  path TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL,
                  mime TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
                  project TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL,
                  payload TEXT NOT NULL, error TEXT, created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY, signature TEXT NOT NULL,
                  jobs TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notes (project TEXT NOT NULL, node TEXT NOT NULL,
                  note TEXT NOT NULL, PRIMARY KEY(project,node));
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        return db

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='paused',error=?,updated=? WHERE status IN ('running','queued')",
                       (json.dumps({"message": "上次进程已停止，未完成任务暂停；请核对后恢复原任务"}, ensure_ascii=False), time.time()))

    def file(self, ident):
        valid_uuid(ident)
        with self.connect() as db:
            row = db.execute("SELECT * FROM files WHERE id=?", (ident,)).fetchone()
        if not row:
            raise ValueError("本地素材不存在，请重新选择文件")
        return dict(row)

    def job(self, ident):
        valid_uuid(ident)
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (ident,)).fetchone()
        if not row:
            raise ValueError("任务不存在")
        job = dict(row)
        job["payload"] = json.loads(job["payload"])
        job["error"] = json.loads(job["error"]) if job["error"] else None
        return job

    def jobs(self):
        with self.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM jobs ORDER BY created DESC LIMIT 300")]
        return [self.job(i) for i in ids]

    def save(self, job, status=None, error=None):
        if status:
            job["status"] = status
        job["error"] = error
        with self.connect() as db:
            db.execute("UPDATE jobs SET payload=?,status=?,error=?,updated=? WHERE id=?",
                       (json.dumps(job["payload"], ensure_ascii=False), job["status"],
                        json.dumps(error, ensure_ascii=False) if error else None, time.time(), job["id"]))

    def add_subjects(self, project, groups, batch_id):
        valid_uuid(project)
        valid_uuid(batch_id)
        if not isinstance(groups, list) or not 1 <= len(groups) <= 200:
            raise ValueError("每批需包含 1–200 个主体")
        checked = []
        for group in groups:
            title = text(group.get("title"))
            description = group.get("description", "")
            if not isinstance(description, str) or len(description) > 3000:
                raise ValueError("主体描述最多 3000 字")
            files = group.get("files")
            if not isinstance(files, list) or not 1 <= len(files) <= 30 or len(set(files)) != len(files):
                raise ValueError("每组需 1–30 张不重复图片（应用上限）")
            assets = [self.file(f) for f in files]
            if any(not Path(a["path"]).is_file() for a in assets):
                raise ValueError("素材文件已丢失")
            signature = json.dumps([project, title, description, [a["sha256"] for a in assets]], ensure_ascii=False)
            fingerprint = hashlib.sha256(signature.encode()).hexdigest()
            checked.append((title, description, assets, fingerprint))
        batch_signature = hashlib.sha256(json.dumps([c[3] for c in checked]).encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
            if old:
                if old["signature"] != batch_signature:
                    raise ValueError("同一批次标识不能用于不同内容")
                return json.loads(old["jobs"])
            ids = []
            for title, description, assets, fingerprint in checked:
                old = db.execute("SELECT id FROM jobs WHERE fingerprint=?", (fingerprint,)).fetchone()
                if old:
                    ids.append(old[0])
                    continue
                ident = new_id()
                payload = {"description": description, "assets": [
                    {"fileId": a["id"], "resourceId": new_id(), "nodeId": node_id(),
                     "updateId": new_id(), "submitId": new_id(), "uploadStarted": False,
                     "uploaded": False, "nodeStarted": False, "saved": False} for a in assets],
                    "nodeId": node_id(), "updateId": new_id(), "elementStarted": False,
                    "done": False}
                now = time.time()
                db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (ident, fingerprint, "subject", project, title, "queued",
                            json.dumps(payload, ensure_ascii=False), None, now, now))
                ids.append(ident)
            db.execute("INSERT INTO batches VALUES(?,?,?)", (batch_id, batch_signature, json.dumps(ids)))
            return ids

    def add_download(self, project, resource, media_type):
        valid_uuid(project)
        valid_uuid(resource)
        if media_type not in {"image", "video", "audio"}:
            raise ValueError("只支持媒体素材")
        fingerprint = f"download:{project}:{resource}"
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT id FROM jobs WHERE fingerprint=?", (fingerprint,)).fetchone()
            if old:
                return old[0]
            ident, now = new_id(), time.time()
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)", (ident, fingerprint, "download",
                       project, "下载 " + resource, "queued", json.dumps({"resourceId": resource,
                       "mediaType": media_type}), None, now, now))
        return ident

    def resume(self, ident):
        valid_uuid(ident)
        with self.connect() as db:
            cursor = db.execute("UPDATE jobs SET status='queued',error=NULL,updated=? WHERE id=? AND status IN ('paused','failed')",
                                (time.time(), ident))
            if not cursor.rowcount:
                raise ValueError("只能恢复已暂停或失败的任务")

    def pause_queued(self, ident=None):
        if ident is not None:
            valid_uuid(ident)
        with self.connect() as db:
            sql = "UPDATE jobs SET status='paused',error=?,updated=? WHERE status='queued'"
            params = [json.dumps({"message": "用户暂停等待中的任务；需要时可恢复"}, ensure_ascii=False), time.time()]
            if ident is not None:
                sql += " AND id=?"
                params.append(ident)
            return db.execute(sql, params).rowcount

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET status='running',updated=? WHERE id=?", (time.time(), row[0]))
        return self.job(row[0])


def observed_node(cli, project, ident):
    data = cli.call(["node", "show", "--project-id", project, "--node-id", ident])
    for row in data.get("nodes", []):
        if row.get("nodeId") == ident or (row.get("node") or {}).get("nodeId") == ident:
            if row.get("node"):
                return row["node"]
            if row.get("result") == "NOT_FOUND":
                return None
            raise CLIError("节点查询结果不确定；请在原画布核对", action="inspect", uncertain=True)
    raise CLIError("节点查询缺少结果；不能认定保存成功", action="inspect", uncertain=True)


class Worker:
    def __init__(self, store, cli):
        self.store, self.cli = store, cli
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True, name="upload-queue")

    def loop(self):
        while not self.stop.is_set():
            try:
                job = self.store.claim()
                if job:
                    self.process(job)
                    continue
            except Exception:
                # Keep thread alive; never dump raw CLI outputs or private payloads.
                print("队列内部错误，请检查本地数据库及磁盘空间", flush=True)
            self.wake.wait(2)
            self.wake.clear()

    def process(self, job):
        try:
            if job["kind"] == "subject":
                self.subject(job)
            elif job["kind"] == "download":
                self.download(job)
            else:
                raise ValueError("未知任务类型")
            self.store.save(job, "success")
        except CLIError as error:
            self.store.save(job, "paused", error.info)
        except Exception as error:
            self.store.save(job, "failed", {"message": str(error)[:800]})

    def subject(self, job):
        p, project = job["payload"], job["project"]
        if not self.cli.call(["auth", "status"]).get("loggedIn"):
            raise CLIError("尚未登录，请完成授权后恢复此任务", code=11, action="login")
        for asset in p["assets"]:
            if self.stop.is_set():
                raise CLIError("程序正在停止，任务已暂停", action="resume")
            file = self.store.file(asset["fileId"])
            if not asset["uploaded"]:
                if asset["uploadStarted"]:
                    # A lost response never results in a blind upload replay.
                    remote = self.cli.call(["resource", "get", asset["resourceId"], "--project-id", project])
                    if remote.get("status") != "success" or remote.get("type") != "image":
                        raise CLIError("原素材未确认可用，暂不重复上传；请核对原画布", action="inspect")
                else:
                    asset["uploadStarted"] = True
                    self.store.save(job)
                    remote = self.cli.call(["resource", "upload", "--project-id", project,
                        "--resource-id", asset["resourceId"], "--file", file["path"],
                        "--name", file["name"], "--import-kind", "local_upload"], timeout=600)
                    if remote.get("resourceId") != asset["resourceId"]:
                        raise CLIError("上传响应身份不匹配，已停止", action="inspect", uncertain=True)
                asset["uploaded"] = True
                self.store.save(job)
            remote = self.cli.call(["resource", "get", asset["resourceId"], "--project-id", project])
            if remote.get("status") != "success" or remote.get("type") != "image":
                raise CLIError("素材尚未成功或类型不适用，稍后恢复继续检查（不会重复上传）", action="resume")
            if not asset["saved"]:
                existing = observed_node(self.cli, project, asset["nodeId"]) if asset["nodeStarted"] else None
                if existing is None:
                    asset["nodeStarted"] = True
                    self.store.save(job)
                    self.cli.call(["node", "create", "image", "--project-id", project,
                        "--node-id", asset["nodeId"], "--update-id", asset["updateId"],
                        "--submit-id", asset["submitId"], "--resource-id", asset["resourceId"],
                        "--import-kind", "local_upload", "--title", file["name"]])
                    existing = observed_node(self.cli, project, asset["nodeId"])
                if not existing or existing.get("type") != "image" or not any(
                        r.get("resourceId") == asset["resourceId"] and r.get("status") == "success"
                        for r in existing.get("resources", [])):
                    raise CLIError("图片节点未回读到成功素材，已停止", action="inspect", uncertain=True)
                asset["saved"] = True
                self.store.save(job)
            else:
                # A collaborator may have changed/deleted a source while this
                # job was paused. Do not blindly bind a stale saved source.
                existing = observed_node(self.cli, project, asset["nodeId"])
                if not existing or existing.get("type") != "image" or not any(
                        r.get("resourceId") == asset["resourceId"] and r.get("status") == "success"
                        for r in existing.get("resources", [])):
                    raise CLIError("已保存的来源节点发生变化，请在原画布核对，不自动覆盖", action="inspect")
        existing = observed_node(self.cli, project, p["nodeId"]) if p["elementStarted"] else None
        if existing is None:
            p["elementStarted"] = True
            self.store.save(job)
            args = ["node", "create", "element", "--project-id", project, "--node-id", p["nodeId"],
                    "--update-id", p["updateId"], "--title", job["title"],
                    "--main", p["assets"][0]["nodeId"]]
            if p["description"]:
                args += ["--description", p["description"]]
            for a in p["assets"][1:]:
                args += ["--auxiliary", a["nodeId"]]
            self.cli.call(args)
            existing = observed_node(self.cli, project, p["nodeId"])
        bindings = (existing or {}).get("subjectBindings") or {}
        if not existing or existing.get("type") != "element" or (bindings.get("main") or {}).get("id") != p["assets"][0]["nodeId"]:
            raise CLIError("主体主素材绑定未确认，已停止", action="inspect", uncertain=True)
        expected = {a["nodeId"] for a in p["assets"][1:]}
        if {a.get("id") for a in bindings.get("auxiliaries", [])} != expected:
            raise CLIError("主体辅助素材绑定未确认，已停止", action="inspect", uncertain=True)
        p["done"] = True

    def download(self, job):
        p, project = job["payload"], job["project"]
        remote = self.cli.call(["resource", "get", p["resourceId"], "--project-id", project])
        if remote.get("status") != "success" or remote.get("type") != p["mediaType"]:
            raise CLIError("素材未成功或类型已变化，不能下载", action="inspect")
        directory = self.store.root / "downloads" / job["id"]
        directory.mkdir(exist_ok=True)
        data = self.cli.call(["resource", "download", p["resourceId"], "--project-id", project,
                              "--output", str(directory)], timeout=600)
        path = Path(data.get("path", "")).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise CLIError("下载结果路径不合法或文件不存在", action="inspect")
        if path.stat().st_size != data.get("size"):
            raise CLIError("下载文件大小与返回值不匹配", action="inspect")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != data.get("sha256"):
            raise CLIError("下载校验失败，不能作为成功文件交付", action="inspect")
        with path.open("rb") as stream:
            mime = media_mime(stream.read(32), path.suffix)
        p.update(path=str(path), name=path.name, mime=mime, size=data["size"])


class App:
    def __init__(self, store, cli):
        self.store, self.cli = store, cli
        self.assets = VideoAssets(store)
        self.session, self.csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.worker = Worker(store, cli)
        self.login_lock = threading.Lock()
        self.login = {"status": "idle"}

    def start_login(self):
        with self.login_lock:
            if self.login.get("status") == "waiting":
                return self.login
            state = self.cli.call(["auth", "status"])
            if state.get("loggedIn"):
                self.login = {"status": "logged_in"}
                return self.login
            data = self.cli.call(["auth", "login"])
            challenge = data.get("challenge") or {}
            url = challenge.get("verificationUriComplete") or challenge.get("verificationUri")
            parsed = urlsplit(url or "")
            if parsed.scheme != "https" or parsed.hostname != "jimeng.jianying.com" or not challenge.get("deviceCode"):
                raise CLIError("授权响应不符合预期，已停止", action="inspect")
            self.login = {"status": "waiting", "url": url, "expiresAt": challenge.get("expiresAt")}
            # Authorization data stays in memory only, never in SQLite/logs.
            def wait():
                try:
                    result = self.cli.call(["auth", "wait", "--device-code", challenge["deviceCode"],
                                            "--timeout", "10m"], timeout=620)
                    self.login = {"status": result.get("status", "unknown")}
                except CLIError as error:
                    self.login = {"status": "failed", "error": error.info}
            threading.Thread(target=wait, daemon=True).start()
            return dict(self.login)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    media_sources = "'self' blob:"

    def setup(self):
        super().setup()
        self.connection.settimeout(60)

    @property
    def app(self):
        return self.server.app

    @property
    def session_cookie_name(self):
        # Browser cookies are host-scoped, not port-scoped. Separate local
        # test/alternate-port instances must not invalidate one another.
        return "dm_session_" + str(self.server.server_port)

    def log_message(self, fmt, *args):
        pass  # Do not log private paths, authorization URLs, or prompts.

    def headers_common(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; media-src " + self.media_sources + "; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

    def json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.headers_common()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self, mutate=False):
        host = self.headers.get("Host", "")
        port = self.server.server_port
        if host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            raise PermissionError("只允许本机访问")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise PermissionError("不允许跨站请求")
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        name = self.session_cookie_name
        if not cookie.get(name) or not secrets.compare_digest(cookie[name].value, self.app.session):
            raise PermissionError("请先打开管理台首页")
        if mutate:
            if self.headers.get("Origin") not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
                raise PermissionError("请求来源不合法")
            if not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), self.app.csrf):
                raise PermissionError("页面会话已过期，请刷新")

    def do_GET(self):
        try:
            self.get()
        except CLIError as error:
            self.json({"error": error.info}, 502)
        except PermissionError as error:
            self.json({"error": {"message": str(error)}}, 403)
        except (ValueError, KeyError) as error:
            self.json({"error": {"message": str(error)}}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.json({"error": {"message": "本地服务错误，请检查磁盘和配置"}}, 500)

    def get(self):
        path = urlsplit(self.path).path
        query = parse_qs(urlsplit(self.path).query)
        if path in {"/health", "/favicon.ico"}:
            port = self.server.server_port
            if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"} or self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise PermissionError("只允许本机访问")
            if path == "/health":
                return self.json({"application": "dreamina-local-manager", "workspace": str(ROOT), "ready": True})
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path in {"/", "/app.js", "/style.css"}:
            port = self.server.server_port
            if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                raise PermissionError("只允许本机访问")
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise PermissionError("不允许跨站访问")
            filename = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}[path]
            body = (ROOT / "web" / filename).read_bytes()
            self.send_response(200)
            self.headers_common()
            if path == "/":
                self.send_header("Set-Cookie", f"{self.session_cookie_name}={self.app.session}; HttpOnly; SameSite=Strict; Path=/")
            self.send_header("Content-Type", {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8"}[filename])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.authorized()
        if path == "/api/session":
            return self.json({"csrf": self.app.csrf, "dataDirectory": str(self.app.store.root), "videoAssets": True})
        if path == "/api/assets":
            return self.json(self.app.assets.listing(project=query.get("project", [""])[0],
                search=query.get("search", [""])[0], offset=int(query.get("offset", ["0"])[0])))
        if path == "/api/assets/export":
            return self.json(self.app.assets.export())
        if path == "/api/status":
            version = self.app.cli.call(["version"])
            state = self.app.cli.call(["auth", "status"])
            account = self.app.cli.call(["auth", "account"]) if state.get("loggedIn") else None
            return self.json({"version": version, "auth": state, "account": account, "login": self.app.login})
        if path == "/api/canvases":
            args = ["canvas", "ls", "--limit", "100"]
            if query.get("cursor"):
                args += ["--cursor", query["cursor"][0]]
            return self.json(self.app.cli.call(args))
        if path == "/api/nodes":
            project = valid_uuid(query.get("project", [""])[0])
            kind = query.get("type", ["video"])[0]
            if kind not in {"video", "element"}:
                raise ValueError("不支持的节点类型")
            offset = int(query.get("offset", ["0"])[0])
            if not 0 <= offset <= 1000:
                raise ValueError("请收窄筛选范围，已达到 CLI 分页上限")
            args = ["node", "find", "--project-id", project, "--type", kind, "--limit", "50", "--offset", str(offset)]
            if query.get("name") and query["name"][0].strip():
                args += ["--name", text(query["name"][0])]
            if query.get("status") and query["status"][0]:
                status = query["status"][0]
                if status not in {"empty", "running", "success", "partial_success", "failed", "canceled", "unknown"}:
                    raise ValueError("状态筛选不合法")
                args += ["--status", status]
            data = self.app.cli.call(args)
            with self.app.store.connect() as db:
                notes = {r[0]: r[1] for r in db.execute("SELECT node,note FROM notes WHERE project=?", (project,))}
            for item in data.get("items", []):
                item["localNote"] = notes.get(item.get("nodeId"), "")
            return self.json(data)
        if path == "/api/node":
            project = valid_uuid(query.get("project", [""])[0])
            ident = valid_node(query.get("node", [""])[0])
            return self.json({"node": observed_node(self.app.cli, project, ident)})
        if path == "/api/jobs":
            return self.json({"items": self.app.store.jobs()})
        if path.startswith("/media/"):
            ident = valid_uuid(path.split("/")[-1])
            job = self.app.store.job(ident)
            if job["kind"] != "download" or job["status"] != "success":
                raise ValueError("下载尚未成功")
            p = job["payload"]
            file = Path(p["path"]).resolve()
            if not file.is_relative_to(self.app.store.root / "downloads" / ident) or not file.is_file():
                raise ValueError("缓存文件已丢失，请检查数据目录")
            return self.serve_media(file, p["mime"], query.get("download", [""])[0] == "1")
        self.json({"error": {"message": "接口不存在"}}, 404)

    def serve_media(self, path, mime, download=False):
        size = path.stat().st_size
        start, end = 0, size - 1
        partial = self.headers.get("Range")
        if partial:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", partial)
            if not match or not any(match.groups()) or not size:
                return self.range_error(size)
            a, b = match.groups()
            if a:
                start = int(a)
                end = min(int(b), size - 1) if b else size - 1
            else:
                length = int(b)
                if not length:
                    return self.range_error(size)
                start = max(0, size - length)
            if start >= size or end < start:
                return self.range_error(size)
        self.send_response(206 if partial else 200)
        self.headers_common()
        self.send_header("Content-Type", mime)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(max(0, end - start + 1)))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            from urllib.parse import quote
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(path.name))
        self.end_headers()
        with path.open("rb") as stream:
            stream.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = stream.read(min(left, 1024 * 1024))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def range_error(self, size):
        self.send_response(416)
        self.send_header("Content-Range", f"bytes */{size}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def read_json(self):
        if self.headers.get_content_type() != "application/json":
            raise ValueError("请求需使用 JSON")
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 2 * 1024 * 1024:
            raise ValueError("请求大小不合法")
        data = json.loads(self.rfile.read(size))
        if not isinstance(data, dict):
            raise ValueError("请求内容格式错误")
        return data

    def do_POST(self):
        try:
            self.authorized(mutate=True)
            self.post()
        except CLIError as error:
            self.json({"error": error.info}, 502)
        except PermissionError as error:
            self.close_connection = True
            self.json({"error": {"message": str(error)}}, 403)
        except (ValueError, KeyError, TypeError) as error:
            self.close_connection = True
            self.json({"error": {"message": str(error)}}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.close_connection = True
            self.json({"error": {"message": "本地操作失败，请检查磁盘或数据库"}}, 500)

    def post(self):
        path = urlsplit(self.path).path
        if path == "/api/upload":
            return self.upload()
        data = self.read_json()
        if path == "/api/assets/import":
            return self.json(self.app.assets.import_snapshot(data))
        if path == "/api/assets/projects":
            return self.json({"projects": self.app.assets.set_projects(data.get("projects"))})
        if path == "/api/subjects":
            ids = self.app.store.add_subjects(data.get("project"), data.get("groups"), data.get("batchId"))
            self.app.worker.wake.set()
            return self.json({"jobIds": ids}, 202)
        if path == "/api/resume":
            self.app.store.resume(data.get("jobId"))
            self.app.worker.wake.set()
            return self.json({"ok": True}, 202)
        if path == "/api/pause":
            count = self.app.store.pause_queued(data.get("jobId"))
            return self.json({"paused": count, "message": "仅暂停尚未开始的任务；正在执行的操作不取消"})
        if path == "/api/download":
            ident = self.app.store.add_download(data.get("project"), data.get("resource"), data.get("type"))
            self.app.worker.wake.set()
            return self.json({"jobId": ident}, 202)
        if path == "/api/note":
            project, ident = valid_uuid(data.get("project")), valid_node(data.get("node"))
            note = data.get("note", "")
            if not isinstance(note, str) or len(note) > 3000:
                raise ValueError("备注最多 3000 字")
            with self.app.store.connect() as db:
                db.execute("INSERT INTO notes VALUES(?,?,?) ON CONFLICT(project,node) DO UPDATE SET note=excluded.note",
                           (project, ident, note))
            return self.json({"ok": True})
        if path == "/api/login":
            return self.json(self.app.start_login())
        self.json({"error": {"message": "接口不存在"}}, 404)

    def upload(self):
        if self.headers.get_content_type() != "application/octet-stream":
            raise ValueError("素材需以二进制文件上传")
        query = parse_qs(urlsplit(self.path).query)
        relative = text(query.get("name", [""])[0], 1000).replace("\\", "/")
        name = relative.split("/")[-1]
        if name in {"", ".", ".."} or any(ord(c) < 32 for c in name):
            raise ValueError("文件名不合法")
        suffix = Path(name).suffix.lower()
        if suffix not in IMAGE_EXT:
            raise ValueError("主体只接受 PNG/JPG/WEBP/GIF 图片")
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= MAX_IMAGE:
            raise ValueError("单张图片需大于 0 且不超过 32MB（应用限制）")
        ident = new_id()
        destination = self.app.store.root / "uploads" / (ident + suffix)
        temp = destination.with_suffix(".part")
        digest, head = hashlib.sha256(), b""
        try:
            with temp.open("xb") as stream:
                left = size
                while left:
                    chunk = self.rfile.read(min(left, 1024 * 1024))
                    if not chunk:
                        raise ValueError("上传中断，文件未完整接收")
                    if not head:
                        head = chunk[:32]
                    digest.update(chunk)
                    stream.write(chunk)
                    left -= len(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            mime = media_mime(head)
            expected = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".webp": "image/webp", ".gif": "image/gif"}[suffix]
            if mime != expected:
                raise ValueError("图片文件头与扩展名不符，请检查素材")
            temp.replace(destination)
            with self.app.store.connect() as db:
                db.execute("INSERT INTO files VALUES(?,?,?,?,?,?,?,?)", (ident, name, relative,
                           str(destination), size, digest.hexdigest(), mime, time.time()))
        except Exception:
            temp.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise
        self.json({"id": ident, "name": name, "size": size, "sha256": digest.hexdigest()})


class StateLock:
    """One process per state directory, even when different HTTP ports are used."""
    def __init__(self, directory):
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.stream = (Path(directory) / "manager.lock").open("a+b")
        self.stream.seek(0, 2)
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise RuntimeError("同一数据目录已有管理台运行，请勿重复启动")

    def close(self):
        self.stream.close()


def validate_schema(schema):
    """Fail closed if an upgrade removes a command/flag used by this app."""
    if schema.get("schemaVersion") != "1":
        raise RuntimeError("CLI schema 版本不兼容，请先核对命令")
    expected = {
        ("canvas", "ls"): {"cursor", "limit"},
        ("node", "find"): {"project-id", "type", "status", "offset", "limit", "name"},
        ("node", "show"): {"project-id", "node-id"},
        ("node", "create", "image"): {"project-id", "node-id", "update-id", "submit-id", "resource-id", "import-kind", "title"},
        ("node", "create", "element"): {"project-id", "node-id", "update-id", "main", "auxiliary", "title", "description"},
        ("resource", "upload"): {"project-id", "resource-id", "file", "name", "import-kind"},
        ("resource", "get"): {"project-id"},
        ("resource", "download"): {"project-id", "output"},
        ("auth", "wait"): {"device-code", "timeout"},
    }
    for path, flags in expected.items():
        entry = schema
        for name in path:
            entry = next((c for c in entry.get("subcommands", []) if c.get("name") == name), {})
        if not entry or not flags <= {f.get("name") for f in entry.get("flags", [])}:
            raise RuntimeError("CLI 命令或参数不兼容：" + " ".join(path))


def main():
    parser = argparse.ArgumentParser(description="本地即梦视频与主体管理台")
    parser.add_argument("--port", type=int, default=8765)
    # MSIX-hosted Codex can virtualize LOCALAPPDATA. Use a stable user-home path
    # so double-clicking start.cmd and launching from Codex see the same queue.
    parser.add_argument("--data-dir", default=str(Path.home() / ".dreamina-manager"))
    parser.add_argument("--cli", default=shutil.which("dreamina-canvas") or str(Path.home() / "bin" / "dreamina-canvas.exe"))
    args = parser.parse_args()
    lock = None
    server = None
    app = None
    code = 0
    try:
        lock = StateLock(args.data_dir)
        store = Store(args.data_dir)
        cli = CLI(args.cli)
        cli.call(["version"])
        schema = cli.call(["schema"])
        validate_schema(schema)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
        server.daemon_threads = True
        app = App(store, cli)
        server.app = app
        store.recover()
        app.worker.thread.start()
        print(f"管理台已启动：http://127.0.0.1:{server.server_port}\n数据目录：{store.root}\n按 Ctrl+C 停止。仅本机访问，不提交生成任务。", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止，未完成任务可在下次启动后恢复。", flush=True)
    except (CLIError, RuntimeError, OSError) as error:
        print("启动未完成：" + str(error), flush=True)
        print("如果端口或实例已在使用，请打开原管理台，或使用 start.ps1 -Port 8766。", flush=True)
        code = 1
    finally:
        if app:
            app.worker.stop.set()
            app.worker.wake.set()
            # Never release the directory lock while a worker is still writing.
            app.worker.thread.join()
        if server:
            server.server_close()
        if lock:
            lock.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
