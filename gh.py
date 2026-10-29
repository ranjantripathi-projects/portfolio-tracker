"""Small GitHub helper so the phone app can save your Excel files and settings to the
repo and start the alert bot, without a laptop."""
from __future__ import annotations

import base64
import os

import requests

API = "https://api.github.com"
WORKFLOW = "price-alerts.yml"


def token() -> str:
    return os.getenv("GITHUB_TOKEN", "")


def repo() -> str:
    return os.getenv("GITHUB_REPO", "").strip().strip("/")


def branch() -> str:
    return os.getenv("GITHUB_BRANCH", "main")


def configured() -> bool:
    return bool(token() and repo())


def _headers():
    return {"Authorization": f"Bearer {token()}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def _check(r: requests.Response, what: str):
    if r.status_code >= 400:
        try:
            msg = r.json().get("message", r.text)
        except Exception:
            msg = r.text
        raise RuntimeError(f"GitHub couldn't {what}: {r.status_code} {msg}")
    return r


def list_dir(path: str) -> list[dict]:
    r = requests.get(f"{API}/repos/{repo()}/contents/{path}", headers=_headers(),
                     params={"ref": branch()}, timeout=20)
    if r.status_code == 404:
        return []
    _check(r, f"list {path}")
    return [{"name": i["name"], "path": i["path"], "sha": i["sha"]}
            for i in r.json() if i["type"] == "file"]


def get_file(path: str) -> tuple[bytes | None, str | None]:
    r = requests.get(f"{API}/repos/{repo()}/contents/{path}", headers=_headers(),
                     params={"ref": branch()}, timeout=20)
    if r.status_code == 404:
        return None, None
    _check(r, f"read {path}")
    j = r.json()
    if j.get("content"):
        return base64.b64decode(j["content"]), j["sha"]
    raw = requests.get(j["download_url"], headers=_headers(), timeout=30)   # files > 1 MB
    return _check(raw, f"download {path}").content, j["sha"]


def put_file(path: str, content: bytes, message: str) -> None:
    _, sha = get_file(path)
    body = {"message": message, "content": base64.b64encode(content).decode(), "branch": branch()}
    if sha:
        body["sha"] = sha
    _check(requests.put(f"{API}/repos/{repo()}/contents/{path}", headers=_headers(),
                        json=body, timeout=30), f"save {path}")


def delete_file(path: str, message: str) -> None:
    _, sha = get_file(path)
    if not sha:
        return
    _check(requests.delete(f"{API}/repos/{repo()}/contents/{path}", headers=_headers(),
                           json={"message": message, "sha": sha, "branch": branch()}, timeout=30),
           f"delete {path}")


def run_workflow(mode: str) -> None:
    _check(requests.post(f"{API}/repos/{repo()}/actions/workflows/{WORKFLOW}/dispatches",
                         headers=_headers(), json={"ref": branch(), "inputs": {"mode": mode}},
                         timeout=20), "start the alert bot")


def recent_runs(n: int = 5) -> list[dict]:
    r = requests.get(f"{API}/repos/{repo()}/actions/workflows/{WORKFLOW}/runs",
                     headers=_headers(), params={"per_page": n}, timeout=20)
    if r.status_code == 404:
        return []
    _check(r, "list bot runs")
    return [{"when": x["created_at"], "event": x["event"], "status": x["status"],
             "result": x["conclusion"], "url": x["html_url"]} for x in r.json().get("workflow_runs", [])]
