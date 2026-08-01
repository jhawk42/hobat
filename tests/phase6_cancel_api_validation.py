import json
import time
import os
import urllib.request
import urllib.error
from pathlib import Path

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:9165")
FILENAME = "td-otbr-cli-networkdiag-fetch-all.json"
OUT = Path("/workspaces/tdash/plan/desk/phase6_cancel_api_validation.log")

result = {
    "base": BASE,
    "filename": FILENAME,
    "steps": [],
    "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}

def call(method, path, headers=None, body=None, timeout=20):
    req = urllib.request.Request(
        BASE + path,
        data=body,
        headers=headers or {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, dict(resp.headers), raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        return e.code, dict(e.headers), raw

# Step 1: trigger long-cost async job
status, headers, body = call("GET", f"/api/data/{FILENAME}", headers={"Cache-Control": "no-cache"})
step1 = {"step": "trigger", "status": status, "body": body}
result["steps"].append(step1)
print("trigger:", status, body)

job_id = None
if status == 202:
    try:
        payload = json.loads(body)
        job_id = payload.get("job_id")
    except Exception:
        pass

if not job_id:
    result["outcome"] = "could-not-start-async-job"
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("No job_id; wrote", OUT)
    raise SystemExit(0)

# Step 2: cancel job
status, headers, body = call("DELETE", f"/api/job/{job_id}")
step2 = {"step": "cancel", "job_id": job_id, "status": status, "body": body}
result["steps"].append(step2)
print("cancel:", status, body)

# Step 3: poll job status until terminal
transitions = []
terminal = {"done", "error", "cancelled"}
final_status = None
final_body = None
for i in range(30):
    status, headers, body = call("GET", f"/api/job/{job_id}")
    try:
        payload = json.loads(body)
    except Exception:
        payload = {"raw": body}
    s = payload.get("status")
    transitions.append({"poll": i, "http_status": status, "status": s, "body": payload})
    print(f"poll[{i}]", status, s)
    if s in terminal:
        final_status = s
        final_body = payload
        break
    time.sleep(1)

result["steps"].append({"step": "poll", "job_id": job_id, "transitions": transitions})
result["final_status"] = final_status
result["final_body"] = final_body
result["outcome"] = "pass" if final_status == "cancelled" else "non-cancelled-terminal-or-timeout"
result["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
print("wrote", OUT)
print("outcome:", result["outcome"], "final_status:", final_status)
