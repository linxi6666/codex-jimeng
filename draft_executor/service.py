"""Local, draft-only Dreamina canvas executor.

The HTTP surface deliberately exposes named operations rather than an arbitrary
CLI proxy. It is bound to loopback, requires a launch-time bearer secret, and
contains no quote/run/credit-confirmation path.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable


WORKSPACE = Path(__file__).resolve().parents[1]
STATE_DIR = WORKSPACE / ".data" / "draft-executor"
DEFAULT_CLI = Path.home() / "bin" / "dreamina-canvas.exe"
EXPECTED_MODEL = "seedance_2.0_mini"
EXPECTED_SETTINGS = {"mode": "m2v", "model": EXPECTED_MODEL, "ratio": "9:16", "resolution": "720p", "count": 1}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
NODE_RE = re.compile(r"^node_[a-z0-9]{10}$")
REF_RE = re.compile(r"\{\{node:(node_[a-z0-9]{10})\}\}")
SAFE_TITLE_RE = re.compile(r"^[^\x00-\x1f]{1,160}$")


class ExecutorError(RuntimeError):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.details = details


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _parse_cli(stdout: str, stderr: str, returncode: int) -> dict[str, Any]:
    for raw in (stdout, stderr):
        try:
            value = json.loads(raw.lstrip("\ufeff"))
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and "ok" in value:
            if not value.get("ok") or returncode:
                err = value.get("error") or {}
                raise ExecutorError("cli_rejected", "Dreamina CLI rejected the operation", {
                    "exitCode": returncode,
                    "errorCode": err.get("code"),
                    "requiredAction": err.get("requiredAction"),
                    "requestId": err.get("requestId") or (value.get("meta") or {}).get("requestId"),
                })
            return value
    raise ExecutorError("cli_result_unknown", "CLI result is not safely classifiable; inspect the stable operation before retrying")


class DreaminaCLI:
    """Typed wrapper: no caller-supplied executable or raw command endpoint."""
    def __init__(self, executable: Path | None = None):
        self.executable = executable or Path(os.environ.get("DREAMINA_CANVAS_CLI", DEFAULT_CLI))

    def call(self, args: list[str], timeout: int = 120) -> dict[str, Any]:
        forbidden = {"run", "quote", "confirm", "upscale", "--run", "--yes", "--credit-token", "--credit-ceiling"}
        if any(arg in forbidden for arg in args):
            raise ExecutorError("generation_forbidden", "This local executor only reads or saves drafts")
        try:
            proc = subprocess.run(
                [str(self.executable), "--format", "json", "--non-interactive", *args],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExecutorError("cli_transport_uncertain", f"CLI could not be conclusively read: {type(exc).__name__}") from None
        return _parse_cli(proc.stdout, proc.stderr, proc.returncode)

    def version(self) -> dict[str, Any]:
        return self.call(["version"])

    def auth_status(self) -> dict[str, Any]:
        return self.call(["auth", "status"])

    def show(self, project_id: str, node_ids: list[str]) -> tuple[dict[str, dict[str, Any]], str | None]:
        args = ["node", "show", "--project-id", project_id]
        for node_id in node_ids:
            args.extend(["--node-id", node_id])
        result = self.call(args)
        nodes = {}
        for item in (result.get("data") or {}).get("nodes", []):
            node = item.get("node") or {}
            if item.get("result") == "FOUND" and node.get("nodeId"):
                nodes[node["nodeId"]] = node
        return nodes, (result.get("meta") or {}).get("requestId")

    def edit(self, project_id: str, shot: dict[str, Any]) -> dict[str, Any]:
        return self._save_video("edit", project_id, shot)

    def create(self, project_id: str, shot: dict[str, Any]) -> dict[str, Any]:
        return self._save_video("create", project_id, shot)

    def _save_video(self, operation: str, project_id: str, shot: dict[str, Any]) -> dict[str, Any]:
        args = ["node", operation, "video", "--project-id", project_id,
                "--node-id", shot["nodeId"], "--update-id", shot["updateId"],
                "--title", shot["title"], "--prompt", shot["prompt"],
                "--mode", EXPECTED_SETTINGS["mode"], "--model", EXPECTED_SETTINGS["model"],
                "--ratio", EXPECTED_SETTINGS["ratio"], "--resolution", EXPECTED_SETTINGS["resolution"],
                "--count", "1", "--duration", str(shot["duration"])]
        for ref in shot["refs"]:
            args.extend(["--ref", ref])
        return self.call(args)


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    if not isinstance(plan, dict):
        raise ExecutorError("invalid_plan", "Plan must be a JSON object")
    project_id = str(plan.get("projectId", ""))
    if not UUID_RE.fullmatch(project_id):
        errors.append({"field": "projectId", "error": "must be a canonical UUID"})
    if plan.get("generate") is not False:
        errors.append({"field": "generate", "error": "must be false; generation is not supported by this service"})
    if plan.get("settings") != EXPECTED_SETTINGS:
        errors.append({"field": "settings", "error": f"must equal the confirmed fixed settings {EXPECTED_SETTINGS}"})
    shots = plan.get("shots")
    if not isinstance(shots, list) or not shots:
        errors.append({"field": "shots", "error": "must be a non-empty list"})
        shots = []
    seen: set[str] = set()
    for index, shot in enumerate(shots):
        prefix = f"shots[{index}]"
        if not isinstance(shot, dict):
            errors.append({"field": prefix, "error": "must be an object"})
            continue
        node_id = str(shot.get("nodeId", ""))
        if not NODE_RE.fullmatch(node_id):
            errors.append({"field": prefix + ".nodeId", "error": "invalid node id"})
        if node_id in seen:
            errors.append({"field": prefix + ".nodeId", "error": "duplicate node id"})
        seen.add(node_id)
        try:
            uuid.UUID(str(shot.get("updateId", "")))
        except (ValueError, AttributeError, TypeError):
            errors.append({"field": prefix + ".updateId", "error": "must be a UUID"})
        if not SAFE_TITLE_RE.fullmatch(str(shot.get("title", ""))):
            errors.append({"field": prefix + ".title", "error": "invalid or missing title"})
        prompt = shot.get("prompt")
        shot_key = str(shot.get("shot", ""))
        if not isinstance(prompt, str) or not prompt.strip():
            errors.append({"field": prefix + ".prompt", "error": "must be non-empty text"})
        else:
            expected_first = f"{plan.get('drama', '')}-{plan.get('episode', '')}-{shot_key}"
            if prompt.splitlines()[0] != expected_first:
                errors.append({"field": prefix + ".prompt", "error": f"first line must be {expected_first}"})
            if len(prompt) > 4000:
                errors.append({"field": prefix + ".prompt", "error": "exceeds model prompt limit of 4000 characters"})
        duration = shot.get("duration")
        if not isinstance(duration, int) or isinstance(duration, bool) or not 4 <= duration <= 15:
            errors.append({"field": prefix + ".duration", "error": "must be an integer from 4 to 15"})
        refs = shot.get("refs")
        if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref.startswith("node:") or not NODE_RE.fullmatch(ref[5:]) for ref in refs):
            errors.append({"field": prefix + ".refs", "error": "must be a list of valid node:<id> references"})
            refs = []
        body_ids = set(REF_RE.findall(prompt if isinstance(prompt, str) else ""))
        listed_ids = {ref[5:] for ref in refs}
        if body_ids != listed_ids:
            errors.append({"field": prefix + ".refs", "error": "refs must exactly match node references in prompt"})
        for ref_id in listed_ids:
            if ref_id == node_id:
                errors.append({"field": prefix + ".refs", "error": "a node cannot reference itself"})
    if errors:
        raise ExecutorError("invalid_plan", "Plan validation failed", errors)
    return {"valid": True, "projectId": project_id, "shots": len(shots), "generate": False,
            "settings": EXPECTED_SETTINGS, "planSha256": sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True))}


def node_fingerprint(node: dict[str, Any]) -> str:
    generation = node.get("generation") or {}
    return sha256(json.dumps({"title": node.get("title"), "prompt": generation.get("prompt"),
                              "model": generation.get("model"), "mode": generation.get("mode"),
                              "ratio": generation.get("ratio"), "resolution": generation.get("resolution"),
                              "count": generation.get("outputCount"), "duration": generation.get("durationSeconds"),
                              "refs": [(r.get("kind"), r.get("id")) for r in generation.get("references", [])]},
                             ensure_ascii=False, sort_keys=True))


def check_reference_integrity(node: dict[str, Any], shot: dict[str, Any]) -> list[str]:
    problems = []
    generation = node.get("generation") or {}
    expected = {ref[5:] for ref in shot["refs"]}
    actual = {r.get("id") for r in (generation.get("references") or []) if r.get("kind") == "node"}
    if actual != expected:
        problems.append("generation.references mismatch")
    if not expected.issubset(set(node.get("upstreamNodeIds") or [])):
        problems.append("upstreamNodeIds missing expected edges")
    refs = generation.get("references") or []
    bound: set[str] = set()
    for part in generation.get("promptParts") or []:
        index = part.get("referenceIndex")
        if part.get("kind") == "reference" and isinstance(index, int) and 0 <= index < len(refs):
            bound.add(refs[index].get("id"))
    if not expected.issubset(bound):
        problems.append("promptParts missing one or more expected bindings")
    return problems


class DraftExecutor:
    def __init__(self, cli: DreaminaCLI, state_dir: Path = STATE_DIR):
        self.cli = cli
        self.state_dir = state_dir
        self._write_lock = threading.Lock()

    def status(self) -> dict[str, Any]:
        version = self.cli.version()
        auth = self.cli.auth_status()
        return {"ok": True, "version": (version.get("data") or {}).get("version"),
                "loggedIn": (auth.get("data") or {}).get("loggedIn") is True,
                "profile": (auth.get("data") or {}).get("profile"), "writeMode": "draft-only"}

    def inspect(self, project_id: str, node_ids: list[str]) -> dict[str, Any]:
        if not UUID_RE.fullmatch(project_id) or not node_ids or any(not NODE_RE.fullmatch(x) for x in node_ids):
            raise ExecutorError("invalid_identity", "Provide a project UUID and one or more valid node IDs")
        nodes, request_id = self.cli.show(project_id, node_ids)
        results = []
        for node_id in node_ids:
            node = nodes.get(node_id)
            if not node:
                results.append({"nodeId": node_id, "found": False})
                continue
            gen = node.get("generation") or {}
            results.append({"nodeId": node_id, "found": True, "type": node.get("type"), "title": node.get("title"),
                            "status": node.get("status"), "resourceCount": len(node.get("resources") or []),
                            "promptSha256": sha256(str(gen.get("prompt", ""))),
                            "duration": gen.get("durationSeconds"), "references": gen.get("references") or [],
                            "upstreamNodeIds": node.get("upstreamNodeIds") or []})
        return {"projectId": project_id, "nodes": results, "requestId": request_id}

    def save(self, plan: dict[str, Any], allow_overwrite: bool = False) -> dict[str, Any]:
        checked = validate_plan(plan)
        if not (self.cli.auth_status().get("data") or {}).get("loggedIn"):
            raise ExecutorError("not_logged_in", "Dreamina CLI profile is not logged in")
        project_id = checked["projectId"]
        shots = plan["shots"]
        state_path = self.state_dir / f"{project_id}.json"
        state = read_json(state_path, {"projectId": project_id, "mode": "draft-only", "items": {}})
        with self._write_lock:
            current, preflight_request_id = self.cli.show(project_id, [s["nodeId"] for s in shots])
            pending = []
            for shot in shots:
                old = current.get(shot["nodeId"])
                if old:
                    resources = old.get("resources") or []
                    status = old.get("status")
                    if status in {"running", "success", "partial_success"} or resources:
                        raise ExecutorError("protected_existing_output", "Existing generated/running video is protected; it will not be changed", {"nodeId": shot["nodeId"], "status": status})
                    if old.get("type") != "video":
                        raise ExecutorError("target_type_conflict", "Target node exists but is not a video", {"nodeId": shot["nodeId"]})
                    if (old.get("generation") or {}).get("prompt") == shot["prompt"] and node_fingerprint(old) == self._desired_fingerprint(shot):
                        problems = check_reference_integrity(old, shot)
                        if not problems:
                            state["items"][shot["nodeId"]] = {"status": "verified", "promptSha256": sha256(shot["prompt"]), "verifiedAt": time.time()}
                            continue
                    rec = state["items"].get(shot["nodeId"], {})
                    expected_before = shot.get("expectedBeforeSha256")
                    live_before = sha256(str((old.get("generation") or {}).get("prompt", "")))
                    if expected_before and expected_before != live_before and not allow_overwrite:
                        raise ExecutorError("concurrent_edit_conflict", "Target changed since the plan baseline; pass allowOverwrite after reviewing the intended revision", {"nodeId": shot["nodeId"], "expectedBeforeSha256": expected_before, "liveSha256": live_before})
                    if not expected_before and (old.get("generation") or {}).get("prompt") and not allow_overwrite:
                        raise ExecutorError("overwrite_not_authorized", "Existing draft differs; explicit overwrite authorization is required", {"nodeId": shot["nodeId"], "liveSha256": live_before})
                    rec.update({"status": "prepared", "promptSha256": sha256(shot["prompt"]), "beforeSha256": live_before})
                    state["items"][shot["nodeId"]] = rec
                else:
                    rec = state["items"].get(shot["nodeId"], {})
                    if rec.get("status") == "uncertain":
                        raise ExecutorError("uncertain_save", "Prior save response is uncertain; inspect the target before retrying", {"nodeId": shot["nodeId"]})
                    rec.update({"status": "prepared", "promptSha256": sha256(shot["prompt"])})
                    state["items"][shot["nodeId"]] = rec
                pending.append(shot)
            state.update({"projectId": project_id, "mode": "draft-only", "planSha256": checked["planSha256"],
                          "preflightRequestId": preflight_request_id})
            atomic_json(state_path, state)
            saved = []
            for shot in pending:
                rec = state["items"][shot["nodeId"]]
                # Re-check immediately before each write, protecting against edits by a collaborator.
                just_before, req = self.cli.show(project_id, [shot["nodeId"]])
                live = just_before.get(shot["nodeId"])
                if live:
                    if live.get("resources") or live.get("status") in {"running", "success", "partial_success"}:
                        raise ExecutorError("protected_existing_output", "Target gained a generated output during the save; stopped", {"nodeId": shot["nodeId"]})
                    if sha256(str((live.get("generation") or {}).get("prompt", ""))) != rec.get("beforeSha256", sha256("")) and not allow_overwrite:
                        raise ExecutorError("concurrent_edit_conflict", "Target changed during batch; stopped before overwrite", {"nodeId": shot["nodeId"], "requestId": req})
                rec.update({"status": "uncertain", "attemptedAt": time.time()})
                atomic_json(state_path, state)
                try:
                    response = self.cli.edit(project_id, shot) if live else self.cli.create(project_id, shot)
                except ExecutorError as exc:
                    if exc.code == "cli_result_unknown" or exc.code == "cli_transport_uncertain":
                        raise
                    rec["status"] = "rejected"
                    rec["errorCode"] = exc.code
                    atomic_json(state_path, state)
                    raise
                rec["saveRequestId"] = (response.get("meta") or {}).get("requestId")
                rec["savedAt"] = time.time()
                atomic_json(state_path, state)
                reread, read_request = self.cli.show(project_id, [shot["nodeId"]])
                saved_node = reread.get(shot["nodeId"])
                self._verify_saved(saved_node, shot)
                rec.update({"status": "verified", "readbackRequestId": read_request, "verifiedAt": time.time()})
                atomic_json(state_path, state)
                saved.append(shot["nodeId"])
            return {"ok": True, "projectId": project_id, "verified": len(shots), "written": saved,
                    "generate": False, "mode": "draft-only", "stateFile": str(state_path)}

    @staticmethod
    def _desired_fingerprint(shot: dict[str, Any]) -> str:
        return sha256(json.dumps({"title": shot["title"], "prompt": shot["prompt"], "mode": EXPECTED_SETTINGS["mode"],
                                  "model": EXPECTED_SETTINGS["model"], "ratio": EXPECTED_SETTINGS["ratio"],
                                  "resolution": EXPECTED_SETTINGS["resolution"], "count": 1,
                                  "duration": shot["duration"], "refs": [("node", r[5:]) for r in shot["refs"]]},
                                 ensure_ascii=False, sort_keys=True))

    @staticmethod
    def _verify_saved(node: dict[str, Any] | None, shot: dict[str, Any]) -> None:
        if not node:
            raise ExecutorError("readback_missing", "Save response received but node was not found on readback", {"nodeId": shot["nodeId"]})
        gen = node.get("generation") or {}
        expected = {"mode": EXPECTED_SETTINGS["mode"], "model": EXPECTED_SETTINGS["model"], "ratio": EXPECTED_SETTINGS["ratio"],
                    "resolution": EXPECTED_SETTINGS["resolution"], "outputCount": 1, "durationSeconds": shot["duration"]}
        wrong = {k: {"expected": v, "actual": gen.get(k)} for k, v in expected.items() if gen.get(k) != v}
        if node.get("type") != "video" or node.get("title") != shot["title"] or gen.get("prompt") != shot["prompt"]:
            wrong["content"] = "title/type/prompt mismatch"
        wrong.update({f"reference.{i}": p for i, p in enumerate(check_reference_integrity(node, shot))})
        if node.get("resources") or node.get("status") not in {"empty", "draft", None}:
            wrong["status"] = {"expected": "empty draft with no outputs", "actual": node.get("status"), "resourceCount": len(node.get("resources") or [])}
        if wrong:
            raise ExecutorError("readback_validation_failed", "Saved draft failed authoritative readback", {"nodeId": shot["nodeId"], "problems": wrong})


class APIHandler(BaseHTTPRequestHandler):
    server_version = "DreaminaDraftExecutor/0.1"
    executor: DraftExecutor

    def log_message(self, fmt: str, *args: Any) -> None:
        # Do not log request bodies, prompts, IDs, or auth headers.
        print(f"[draft-executor] {self.log_date_time_string()} {self.command} {self.path.split('?')[0]}")

    def _send(self, status: int, obj: dict[str, Any]) -> None:
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        host = self.headers.get("Host", "").lower()
        if not (host.startswith("127.0.0.1:") or host.startswith("localhost:") or host.startswith("[::1]:")):
            return False
        # No browser client is supported. Reject browser-originated requests
        # instead of maintaining a permissive same-machine CORS/CSRF exception.
        if self.headers.get("Origin"):
            return False
        return True

    def do_GET(self) -> None:
        if self.path != "/health":
            self._send(404, {"ok": False, "error": {"code": "not_found"}})
            return
        if not self._authorized():
            self._send(403, {"ok": False, "error": {"code": "forbidden"}})
            return
        try:
            self._send(200, self.executor.status())
        except ExecutorError as exc:
            self._send(503, {"ok": False, "error": {"code": exc.code, "message": str(exc)}})

    def do_POST(self) -> None:
        if not self._authorized():
            self._send(403, {"ok": False, "error": {"code": "forbidden"}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2_000_000:
                raise ExecutorError("invalid_body", "Request body must be 1 byte to 2 MB")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise ExecutorError("invalid_body", "Request body must be a JSON object")
            if self.path == "/v1/inspect":
                result = self.executor.inspect(str(body.get("projectId", "")), body.get("nodeIds", []))
            elif self.path == "/v1/validate":
                result = validate_plan(body.get("plan"))
            elif self.path == "/v1/save":
                result = self.executor.save(body.get("plan"), allow_overwrite=body.get("allowOverwrite") is True)
            else:
                self._send(404, {"ok": False, "error": {"code": "not_found"}})
                return
            self._send(200, result)
        except json.JSONDecodeError:
            self._send(400, {"ok": False, "error": {"code": "invalid_json"}})
        except ExecutorError as exc:
            status = 409 if exc.code in {"concurrent_edit_conflict", "overwrite_not_authorized", "protected_existing_output", "uncertain_save"} else 400
            self._send(status, {"ok": False, "error": {"code": exc.code, "message": str(exc), "details": exc.details}})
        except Exception as exc:
            self._send(500, {"ok": False, "error": {"code": "internal_error", "type": type(exc).__name__}})


def serve(host: str = "127.0.0.1", port: int = 8770) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Refusing non-loopback bind")
    handler = type("BoundAPIHandler", (APIHandler,), {"executor": DraftExecutor(DreaminaCLI())})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    print(json.dumps({"service": "dreamina-draft-executor", "url": f"http://{host}:{port}",
                      "mode": "draft-only", "generation": False}, ensure_ascii=False), flush=True)
    try:
        httpd.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("[draft-executor] stopping", flush=True)
    finally:
        httpd.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Local draft-only Dreamina executor")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()
    serve(args.host, args.port)
