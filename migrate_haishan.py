"""One-off migration from exported Haishan images to Dreamina subjects.

No browser credentials, private APIs, generation, overwrite, or deletion.
Default is a read-only plan. Explicit --execute uploads; --prepare-only stages.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import json
import re
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from manager import (CLI, CLIError, IMAGE_EXT, MAX_IMAGE, StateLock, Store,
                     Worker, new_id, observed_node, valid_uuid, validate_schema)

KINDS = ("人设", "场景", "道具")
ALIASES = {"角色": "人设", "人物": "人设", "主体": "人设"}


def component(value):
    value = str(value).strip()
    if not value or len(value) > 70 or re.search(r'[<>:"/\\|?*\x00-\x1f]', value):
        raise ValueError("名称不能为空、超过70字或含文件名非法字符")
    if value.endswith((".", " ")) or value in {".", ".."}:
        raise ValueError("名称不能是目录跳转或以点结尾")
    return value


def make_title(drama, kind, name):
    kind = ALIASES.get(kind, kind)
    if kind not in KINDS:
        raise ValueError("分类必须为人设、场景、道具")
    return f"{component(drama)}-{kind}-{component(name)}"


def load_groups(drama, source_dir=None, manifest=None):
    groups = {}

    def add(kind, name, source, description=""):
        kind = ALIASES.get(kind, kind)
        title = make_title(drama, kind, name)
        if len(description) > 3000:
            raise ValueError("描述最多3000字")
        if len(title) > 170:
            raise ValueError("完整名称过长，请缩短剧名或素材名称")
        group = groups.setdefault(title, {"title": title, "kind": kind, "description": description, "sources": []})
        if group["description"] != description:
            raise ValueError(f"同一主体的描述不一致：{title}")
        if source not in group["sources"]:
            group["sources"].append(source)

    if source_dir:
        root = Path(source_dir).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("素材来源须为文件夹")
        for file in sorted(root.rglob("*")):
            if not file.is_file() or file.suffix.lower() not in IMAGE_EXT:
                continue
            relative = file.relative_to(root)
            if not file.resolve().is_relative_to(root):
                raise ValueError("来源目录包含指向外部的文件链接")
            # Category/name/views or category/name.png. Never guess categories.
            if len(relative.parts) < 2:
                raise ValueError("图片需要放在分类目录中：人设/名称/图片.png 或 人设/名称.png")
            name = relative.parts[1] if len(relative.parts) > 2 else file.stem
            add(relative.parts[0], name, str(file.resolve()))
    else:
        path = Path(manifest).resolve(strict=True)
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not {"kind", "name", "source"} <= set(reader.fieldnames or []):
                raise ValueError("CSV 必须包含 kind,name,source 列，description 可选")
            for row in reader:
                source = (row["source"] or "").strip()
                if not source:
                    raise ValueError("CSV 来源不能为空")
                if not source.startswith("https://"):
                    if re.match(r"^[a-z]+://", source, re.I):
                        raise ValueError("网络下载只支持 HTTPS")
                    source = str((path.parent / source).resolve(strict=True))
                    if not Path(source).is_file():
                        raise ValueError("CSV 本地来源不是文件")
                add(row["kind"].strip(), row["name"], source, row.get("description") or "")
    result = sorted(groups.values(), key=lambda g: (KINDS.index(g["kind"]), g["title"]))
    if not result:
        raise ValueError("没有找到可迁移图片")
    if any(len(g["sources"]) > 30 for g in result):
        raise ValueError("每个主体最多30张图，请先选好主图与辅助图")
    return result


def public_https(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("只接受无内嵌凭据的 HTTPS 素材地址")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError:
        raise ValueError("素材域名无法解析") from None
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("不允许下载本机或内网地址")


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def image_extension(head):
    # Never trust a URL suffix or Content-Type (e.g. a login page named .png).
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head[:6] in {b"GIF87a", b"GIF89a"}:
        return ".gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    raise ValueError("来源不是支持的图片，可能返回了登录页；请从海扇导出图片")


def atomic_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stage(store, group):
    """Keep original files; stage standardized names with durable SHA256 receipts."""
    directory = store.root / "renamed" / group["title"]
    directory.mkdir(parents=True, exist_ok=True)
    receipt = directory / "receipt.json"
    prior = json.loads(receipt.read_text(encoding="utf-8")) if receipt.exists() else []
    if not isinstance(prior, list) or any(not isinstance(r, dict) or not
            all(isinstance(r.get(k), str) for k in ("name", "sourceHash", "sha256")) for r in prior):
        raise ValueError("暂存回执格式不正确，请保留原文件并核对，不要直接重传")
    if len(prior) > len(group["sources"]):
        raise ValueError("已有迁移记录的素材数量改变，停止以避免创建重复主体")
    files = []
    for index, source in enumerate(group["sources"]):
        identity = hashlib.sha256(source.encode()).hexdigest()  # No URLs saved in receipts.
        if index < len(prior):
            record = prior[index]
            if Path(record["name"]).name != record["name"]:
                raise ValueError("暂存回执包含非法路径，已停止")
            path = directory / record["name"]
            if (record["sourceHash"] != identity or not path.is_file()
                    or sha(path) != record["sha256"]
                    or (not source.startswith("https://") and sha(Path(source)) != record["sha256"])):
                raise ValueError("素材或暂存文件已变化，请核对原迁移记录；不会自动重传")
        else:
            part = directory / f"{index + 1:02d}.part"
            try:
                if source.startswith("https://"):
                    public_https(source)
                    stream = build_opener(SafeRedirect()).open(
                        Request(source, headers={"User-Agent": "Haishan-Migration/1.0"}), timeout=60)
                else:
                    stream = Path(source).open("rb")
                with stream, part.open("wb") as output:
                    size = 0
                    while block := stream.read(128 * 1024):
                        size += len(block)
                        if size > MAX_IMAGE:
                            raise ValueError("图片超过本工具32MiB上限")
                        output.write(block)
                if size == 0:
                    raise ValueError("素材文件为空")
                with part.open("rb") as inp:
                    ext = image_extension(inp.read(32))
                path = directory / f"{group['title']}-{index + 1:02d}{ext}"
                if path.exists():
                    # Recover the narrow crash window between rename and receipt.
                    if sha(path) != sha(part):
                        raise ValueError("目标文件已存在且内容不同，拒绝覆盖")
                    part.unlink()
                else:
                    part.replace(path)
                record = {"name": path.name, "sha256": sha(path), "sourceHash": identity}
                prior.append(record)
                atomic_json(receipt, prior)
            except ValueError:
                raise
            except Exception:
                # Network exceptions can contain signed URLs; do not print them.
                raise ValueError("下载/复制未完成；请检查网络和来源权限，不要提供Cookie或密码") from None
            finally:
                if part.exists():
                    part.unlink()
        with store.connect() as db:
            row = db.execute("SELECT id FROM files WHERE path=? AND sha256=?", (str(path), record["sha256"])).fetchone()
            if row:
                ident = row[0]
            else:
                ident = new_id()
                mime = {".png": "image/png", ".jpg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}[path.suffix]
                db.execute("INSERT INTO files VALUES(?,?,?,?,?,?,?,?)", (ident, path.name, path.name,
                           str(path), path.stat().st_size, record["sha256"], mime, time.time()))
        files.append(ident)
    return {"title": group["title"], "description": group["description"], "files": files}


def verify(cli, job):
    """Read only: a deleted/changed successful subject must not be silently recreated."""
    p = job["payload"]
    node = observed_node(cli, job["project"], p["nodeId"])
    bindings = (node or {}).get("subjectBindings") or {}
    if (not node or node.get("type") != "element" or node.get("title") != job["title"]
            or (bindings.get("main") or {}).get("id") != p["assets"][0]["nodeId"]
            or {a.get("id") for a in bindings.get("auxiliaries", [])} != {a["nodeId"] for a in p["assets"][1:]}):
        raise ValueError("主体标题或主/辅助素材回读不一致，停止；请检查原画布")
    for asset in p["assets"]:
        source = observed_node(cli, job["project"], asset["nodeId"])
        if not source or source.get("type") != "image" or not any(
                r.get("resourceId") == asset["resourceId"] and r.get("status") == "success"
                for r in source.get("resources", [])):
            raise ValueError("主体来源图片未确认成功，请检查原画布")


def migrate(store, cli, project, groups, resume=False):
    valid_uuid(project)
    # A changed title's contents must not silently create a second subject.
    with store.connect() as db:
        for g in groups:
            rows = db.execute("SELECT payload FROM jobs WHERE project=? AND title=?", (project, g["title"])).fetchall()
            expected = [store.file(f)["sha256"] for f in g["files"]]
            for row in rows:
                p = json.loads(row[0])
                actual = [store.file(a["fileId"])["sha256"] for a in p["assets"]]
                if actual != expected or p["description"] != g["description"]:
                    raise ValueError("同名主体已有不同迁移内容，停止以避免重复上传")
    ids = store.add_subjects(project, groups, new_id())
    worker = Worker(store, cli)  # Run synchronously under our own process lock.
    for ident in ids:
        job = store.job(ident)
        if job["status"] == "success":
            verify(cli, job)
            print(f"已核对，跳过重复上传：{job['title']}", flush=True)
            continue
        if job["status"] in {"paused", "failed", "running"} and not resume:
            raise ValueError("存在未完成迁移；核对错误后用 --resume 继续原任务")
        store.save(job, "running")
        worker.process(job)
        job = store.job(ident)
        if job["status"] != "success":
            error = job["error"] or {}
            raise CLIError(f"迁移暂停：{job['title']}；{error.get('message', '请核对原任务')}",
                           code=error.get("exitCode"), action=error.get("requiredAction"))
        verify(cli, job)
        print(f"上传与主体绑定已验证：{job['title']}", flush=True)
    return [{"title": store.job(i)["title"], "projectId": project,
             "nodeId": store.job(i)["payload"]["nodeId"], "jobId": i} for i in ids]


def main(argv=None):
    parser = argparse.ArgumentParser(description="海扇图片迁移；默认只预览，不下载、不上传")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--source-dir", help="已导出目录，结构：人设/名称/图片.png，场景/...，道具/...")
    src.add_argument("--manifest", help="UTF-8 CSV 清单；kind,name,source,description")
    parser.add_argument("--drama", default="浪子回头", help="剧名简称")
    parser.add_argument("--project-id", help="即梦目标画布；执行上传时必须明确提供")
    parser.add_argument("--limit", type=int, default=3, help="测试默认只取前3个主体；0表示全部")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--prepare-only", action="store_true", help="只下载/复制并重命名，不上传")
    action.add_argument("--execute", action="store_true", help="明确执行上传并创建主体，不生成")
    parser.add_argument("--resume", action="store_true", help="核对后恢复原暂停任务，不更换身份")
    parser.add_argument("--state-dir", help="私人迁移状态目录；切换目录会丢失防重复记录")
    parser.add_argument("--cli", default=str(Path.home() / "bin" / "dreamina-canvas.exe"))
    args = parser.parse_args(argv)
    lock = None
    try:
        if args.limit < 0:
            raise ValueError("limit 不能为负数")
        groups = load_groups(args.drama, args.source_dir, args.manifest)
        total = len(groups)
        if args.limit:
            groups = groups[:args.limit]
        if len(groups) > 200:
            raise ValueError("一次最多200个主体，请分批整理来源目录")
        print(f"计划迁移 {len(groups)}/{total} 个主体（每组第一张按文件名排序的图片为主图）")
        for g in groups:
            print(f"  {g['title']}：{len(g['sources'])} 张")
        if not args.execute and not args.prepare_only:
            print("仅预览，未下载或上传。确认后加 --prepare-only 或 --execute。")
            return 0
        cli = None
        if args.execute:
            if not args.project_id:
                raise ValueError("上传必须显式指定 --project-id，不能猜测目标画布")
            valid_uuid(args.project_id)
            cli = CLI(args.cli)
            cli.call(["version"])
            validate_schema(cli.call(["schema"]))
            if not cli.call(["auth", "status"]).get("loggedIn"):
                raise CLIError("请先完成即梦登录", code=11, action="login")
            cli.call(["auth", "account"])
        directory = Path(args.state_dir) if args.state_dir else Path.home() / ".dreamina-manager" / "migrations" / component(args.drama)
        lock = StateLock(directory)
        store = Store(directory)
        prepared = [stage(store, g) for g in groups]
        if args.execute:
            report = migrate(store, cli, args.project_id, prepared, args.resume)
            atomic_json(store.root / "result.json", report)
            print(f"已验证 {len(report)} 个主体；恢复记录：{store.root / 'result.json'}")
        else:
            print(f"已暂存并重命名 {len(prepared)} 组，未上传：{store.root / 'renamed'}")
        return 0
    except CLIError as error:
        print(f"未完成：{error}；下一步：{error.info.get('requiredAction') or '核对原任务'}", file=sys.stderr)
        return error.info.get("exitCode") or 1
    except (ValueError, OSError, RuntimeError) as error:
        print(f"未完成：{error}", file=sys.stderr)
        return 1
    finally:
        if lock:
            lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
