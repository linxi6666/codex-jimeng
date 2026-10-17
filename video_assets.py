"""Local catalogue of official video-page observations, never canvas nodes.

Only user-visible prompt/metadata is accepted. No browser cookies, signed URLs,
private endpoints, downloads, or generation. This is not an API synchronizer.
"""
import hashlib
import json
import re
import time
import uuid

SOURCE = "jimeng-official-video-page"
FIELDS = {"recordId", "prompt", "date", "duration", "model", "resolution", "ratio"}
DEFAULT_PROJECTS = [{"name": "浪子回头", "aliases": []}]


def validate_projects(items):
    if not isinstance(items, list) or len(items) > 200:
        raise ValueError("最多登记200个剧名简称")
    result, used = [], set()
    for item in items:
        if not isinstance(item, dict) or set(item) - {"name", "aliases"}:
            raise ValueError("项目配置格式不正确")
        name, aliases = item.get("name"), item.get("aliases", [])
        if not isinstance(aliases, list) or len(aliases) > 20:
            raise ValueError("每个剧名最多20个简称")
        terms = [name, *aliases]
        for term in terms:
            if (not isinstance(term, str) or not term.strip() or len(term) > 40
                    or term.strip() == "其他" or re.search(r"[\n\r\x00<>《》【】\[\]：:]", term)):
                raise ValueError("剧名/简称需1–40字，不能用其他或包含换行、括号、冒号")
            key = term.strip().casefold()
            if key in used:
                raise ValueError("剧名或简称重复/冲突，请检查")
            used.add(key)
        result.append({"name": name.strip(), "aliases": [a.strip() for a in aliases]})
    return result


def classify_prompt(prompt, projects):
    """Only anchored, explicit prefixes qualify; never search prompt body."""
    start = prompt.lstrip("\ufeff \t\r\n")
    terms = {term.casefold(): p["name"] for p in projects for term in [p["name"], *p["aliases"]]}
    # An explicit book-title header declares a project, even if not registered.
    match = re.match(r"^《([^《》\r\n]{1,40})》", start)
    if match and match[1].strip() and match[1].strip() != "其他":
        name = match[1].strip()
        return terms.get(name.casefold(), name), "提示词开头的《剧名》"
    match = re.match(r"^(?:剧名|项目)\s*[：:]\s*([^\r\n]{1,40})(?:\r?\n|$)", start)
    if match:
        name = match[1].strip().strip("《》")
        if name and name != "其他":
            return terms.get(name.casefold(), name), "提示词开头的剧名/项目声明"
    for term in sorted(terms, key=len, reverse=True):
        # Require a separator so '浪子回头了...' is not guessed as a title.
        if start.casefold().startswith(term) and re.match(r"^[\s\-—－:：|｜/·]", start[len(term):]):
            return terms[term], "已登记剧名/简称前缀"
        for left, right in (("【", "】"), ("[", "]")):
            if start.casefold().startswith(left + term + right):
                return terms[term], "已登记剧名/简称前缀"
    return "其他", "开头没有可确认的剧名，不从正文猜测"


class VideoAssets:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS video_assets (
                  id TEXT PRIMARY KEY, payload TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS asset_settings (
                  key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            db.execute("INSERT OR IGNORE INTO asset_settings VALUES('projects',?)",
                       (json.dumps(DEFAULT_PROJECTS, ensure_ascii=False),))

    def projects(self):
        with self.store.connect() as db:
            return json.loads(db.execute("SELECT value FROM asset_settings WHERE key='projects'").fetchone()[0])

    def set_projects(self, items):
        checked = validate_projects(items)
        with self.store.connect() as db:
            db.execute("UPDATE asset_settings SET value=? WHERE key='projects'", (json.dumps(checked, ensure_ascii=False),))
        return checked

    def import_snapshot(self, data):
        if not isinstance(data, dict) or data.get("source") != SOURCE or set(data) - {"source", "items"}:
            raise ValueError("清单必须来自官方生成历史的视频模块，不能使用画布节点清单")
        items = data.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 500:
            raise ValueError("每批清单需1–500条视频记录")
        checked, seen = [], set()
        digest = hashlib.sha256(json.dumps(items, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        # Validate the whole batch before writing anything.
        for index, item in enumerate(items):
            if not isinstance(item, dict) or set(item) - FIELDS:
                raise ValueError("清单字段不合法；不接受Cookie、URL或内部接口数据")
            record = {}
            for key in FIELDS - {"recordId"}:
                value = item.get(key, "")
                if not isinstance(value, str) or len(value) > (20000 if key == "prompt" else 120) or "\x00" in value:
                    raise ValueError("提示词或视频元数据格式不正确")
                # Do not persist transient access URLs copied into visible text.
                record[key] = re.sub(r"https?://\S+", "[链接已隐藏]", value)
            ident = item.get("recordId")
            if ident is None:
                # Stable for identical imported snapshots, including duplicate
                # prompts at different positions. Not an official asset identity.
                ident = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{SOURCE}:{digest}:{index}"))
            if not isinstance(ident, str) or str(uuid.UUID(ident)) != ident or ident in seen:
                raise ValueError("本地记录ID须为不重复的小写UUID；不是官方资产ID")
            seen.add(ident)
            checked.append((ident, record))
        added = updated = 0
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            now = time.time()
            for ident, record in checked:
                old = db.execute("SELECT id FROM video_assets WHERE id=?", (ident,)).fetchone()
                updated += bool(old)
                added += not bool(old)
                db.execute("INSERT INTO video_assets VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated=excluded.updated",
                           (ident, json.dumps(record, ensure_ascii=False), now, now))
        return {"added": added, "updated": updated}

    def listing(self, project="", search="", offset=0, limit=50):
        if not 0 <= offset <= 100000 or not 1 <= limit <= 100 or len(search) > 300:
            raise ValueError("分页或搜索条件不合法")
        projects = self.projects()
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM video_assets ORDER BY created DESC,id").fetchall()
        groups, records = {}, []
        for row in rows:
            item = json.loads(row["payload"])
            group, reason = classify_prompt(item["prompt"], projects)
            groups[group] = groups.get(group, 0) + 1
            if (project and group != project) or (search and search.casefold() not in item["prompt"].casefold()):
                continue
            records.append({**item, "recordId": row["id"], "projectName": group, "classificationReason": reason})
        groups.setdefault("其他", 0)
        return {"items": records[offset:offset + limit], "total": len(records), "indexedTotal": len(rows),
                "hasMore": offset + limit < len(records), "offset": offset, "projects": projects,
                "groups": [{"name": k, "count": v} for k, v in sorted(groups.items(), key=lambda x: (x[0] == "其他", x[0]))],
                "source": SOURCE, "coverage": "仅已读取/导入的官方视频详情记录，不是官方全量资产，也不是画布节点"}

    def export(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT id,payload FROM video_assets ORDER BY created,id").fetchall()
        return {"source": SOURCE, "items": [{**json.loads(r["payload"]), "recordId": r["id"]} for r in rows]}
