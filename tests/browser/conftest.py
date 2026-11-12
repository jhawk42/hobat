from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "http://127.0.0.1:9178"


def inventory(directory: Path) -> dict[str, str]:
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file() and not path.name.endswith(("-wal", "-shm"))
    }


@pytest.fixture(scope="session")
def dashboard_server(tmp_path_factory, request):
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 9178))
        except OSError as exc:
            pytest.fail(f"Port 9178 is occupied; refusing to reuse or stop its listener: {exc}")
    baseline = inventory(ROOT / "data")
    scratch = tmp_path_factory.mktemp("browser-dashboard")
    fixtures = json.loads((ROOT / "tests/fixtures/browser_dashboard.json").read_text())
    for filename, payload in fixtures.items():
        (scratch / filename).write_text(json.dumps(payload))
    fixture_hashes = {name: hashlib.sha256((scratch / name).read_bytes()).hexdigest()
                      for name in fixtures}
    with (scratch / "server.log").open("w+") as log:
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "src/td_webserver.py"), "--host", "127.0.0.1",
             "--port", "9178", "--datadir", str(scratch)],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 15
            while True:
                if process.poll() is not None or time.monotonic() >= deadline:
                    log.seek(0)
                    pytest.fail(f"Owned dashboard server failed readiness:\n{log.read()}")
                try:
                    with urllib.request.urlopen(f"{ORIGIN}/tdash.html", timeout=1) as response:
                        assert response.status == 200
                    break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.05)
            yield fixtures
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            with socket.socket() as probe:
                assert probe.connect_ex(("127.0.0.1", 9178)) != 0, "Port 9178 leaked"
            assert inventory(ROOT / "data") == baseline, "Repository cache changed"
            assert {name: hashlib.sha256((scratch / name).read_bytes()).hexdigest()
                    for name in fixtures} == fixture_hashes, "Synthetic cache changed"
            if getattr(request.session, "browser_failed", False):
                artifacts = ROOT / ".pytest-browser-artifacts"
                artifacts.mkdir(exist_ok=True)
                log.flush()
                log.seek(0)
                (artifacts / "server.log").write_text(log.read())


class Dashboard:
    def __init__(self, page, fixtures, scenario):
        self.page = page
        self.fixtures = fixtures
        self.mode = "normal"
        self.active = {"scenario": scenario, "source": "", "dataset": "",
                       "view": "topology", "filter": "all"}
        self.requests = []
        self.errors = []
        self.responses = []
        self.warnings = []
        self.jobs = [{"jobId": "fixture-job", "kind": "collector", "source": "otbr-cli",
                      "task": "fixture", "status": "running", "cancellable": True,
                      "elapsedSeconds": 1, "cancelUrl": "/api/job/fixture-job"},
                     {"jobId": "fixture-job-2", "kind": "collector", "source": "otbr-restapi",
                      "task": "second", "status": "running", "cancellable": True,
                      "elapsedSeconds": 1, "cancelUrl": "/api/job/fixture-job-2"}]
        self.labels = {}
        self.deleted = []
        page.on("pageerror", lambda error: self.errors.append((dict(self.active), str(error))))
        page.on("console", self.console)
        page.on("requestfailed", self.failed)
        page.on("response", lambda response: self.responses.append(
            ({**self.active, "mode": self.mode}, response.status, response.url)))
        page.route("**/*", self.route)

    def console(self, message):
        if message.type == "error":
            # Deliberately injected HTTP errors are checked by their DOM error state.
            if self.mode != "error" or "503" not in message.text:
                self.errors.append((dict(self.active), message.text))
        elif message.type == "warning":
            self.warnings.append((dict(self.active), message.text))

    def failed(self, request):
        if not (request.failure == "net::ERR_ABORTED" and self.mode == "async"
                and urlsplit(request.url).path.startswith(("/api/job/", "/api/data/"))):
            self.errors.append((dict(self.active), request.url, request.failure))

    def route(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path, method = parsed.path, request.method
        self.requests.append((path, method, request.headers))
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.errors.append(("Blocked external request", request.url))
            route.fulfill(status=403, body="external request prohibited")
        elif path == "/api/capabilities" and method == "GET":
            route.fulfill(json={
                "sources": {source: {"state": "cached"} for source in ["otbr-cli", "otbr-restapi"]},
                "files": {name: {"cached": True, "source": (
                    "otbr-restapi" if "restapi" in name else "otbr-cli")}
                    for name in self.fixtures},
            })
        elif path == "/api/device-actions" and method == "GET":
            route.fulfill(json={"enabled": True, "actions": []})
        elif path.startswith("/api/device/") and method in {"GET", "PATCH"}:
            address = path.rsplit("/", 1)[1]
            if method == "PATCH":
                self.labels[address] = request.post_data_json["deviceLabel"]
            route.fulfill(json={"deviceLabel": self.labels.get(address, "")})
        elif path == "/api/jobs" and method in {"GET", "DELETE"}:
            if method == "DELETE":
                self.deleted.append("all")
                self.jobs = []
            route.fulfill(json={"jobs": self.jobs})
        elif path in {"/api/job/fixture-job", "/api/job/fixture-job-2"} and method in {"GET", "DELETE"}:
            if method == "DELETE":
                job_id = path.rsplit("/", 1)[1]
                self.deleted.append(job_id)
                self.jobs = [job for job in self.jobs if job["jobId"] != job_id]
            route.fulfill(json={"status": "running"})
        elif path.startswith("/api/data/") and method == "GET":
            filename = path.rsplit("/", 1)[1]
            if filename not in self.fixtures or "only-if-cached" not in request.headers.get(
                    "cache-control", ""):
                self.errors.append(("Unsafe data request", path, request.headers))
                route.fulfill(status=403, body="cache-only fixture requests required")
            elif self.mode == "error" and "topology" in filename:
                route.fulfill(status=503, json={"error": "Injected fixture failure"})
            elif self.mode == "async" and "topology" in filename:
                route.fulfill(status=202, json={"job_id": "fixture-job"})
            elif self.mode == "empty" and "topology" in filename:
                route.fulfill(json=[])
            elif self.mode == "malformed" and "topology" in filename:
                rows = json.loads(json.dumps(self.fixtures[filename]))
                rows[0]["id"] = {"toString": None}
                route.fulfill(json=rows)
            else:
                route.continue_()
        elif method == "GET" and (path in {
                "/api/catalog", "/tdash.html", "/tdash.css", "/favicon.ico",
        } or path.startswith("/js/")):
            route.continue_()
        else:
            self.errors.append(("Blocked unmatched request", method, path))
            route.fulfill(status=403, body="unmatched API prohibited")

    def select(self, selector, value):
        self.active[selector.lstrip("#")] = value
        self.page.eval_on_selector(selector, """(element, value) => {
            if (![...element.options].some(option => option.value === value && !option.disabled))
                throw new Error(`Not an offered option: ${value}`);
            element.value = value;
            element.dispatchEvent(new Event('change', {bubbles: true}));
        }""", value)

    def choose(self, source="otbr-cli", dataset="otbr_cli_mesh"):
        self.active.update(source=source, dataset=dataset)
        self.select("#datasource-filter", source)
        self.select("#dataset-select", dataset)

    def settled(self):
        self.page.wait_for_function("""() =>
          !document.querySelector('#btn-fetch').disabled &&
          !/^(Loading|Fetching|Cancelling)|still loading/i.test(
            document.querySelector('#fetch-status-line-content').textContent.trim()) &&
          !/^Loading/i.test(document.querySelector('#view-status-line-content').textContent.trim())
        """)

    def sync(self):
        assert self.page.locator("#chk-only-cache").is_checked()
        assert not self.page.locator("#chk-auto-fetch").is_checked()
        assert not self.page.locator("#chk-force-fresh").is_checked()
        self.page.locator("#btn-fetch").evaluate("(button) => button.click()")
        self.settled()

    def view(self, name):
        self.active["view"] = name
        self.page.locator(f"#btn-{name}").evaluate("(button) => button.click()")


@pytest.fixture(params=[(1440, 1000), (390, 844)], ids=["desktop", "mobile"])
def dashboard(request, dashboard_server):
    # Lazy import: ordinary pytest collection requires no browser dependency.
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        if exc.name != "playwright":
            raise
        pytest.fail("Install requirements_browser_test.txt, then run "
                    "`python3 -m playwright install --with-deps chromium`.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport=dict(zip(("width", "height"), request.param)))
        context.tracing.start(screenshots=True, snapshots=True)
        page = context.new_page()
        page.set_default_timeout(10000)
        state = Dashboard(page, dashboard_server, request.node.name)
        page.add_init_script("""(() => {
          const fetchOriginal = window.fetch;
          window.fetch = async (...args) => {
            const response = await fetchOriginal(...args);
            const jsonOriginal = response.json.bind(response);
            response.json = async () => {
              const payload = await jsonOriginal();
              if (window.__heldLabel && String(args[0]).endsWith(window.__heldLabel)) {
                window.__labelBodyWaiting = true;
                await new Promise(resolve => { window.__releaseLabel = resolve; });
              }
              if (window.__holdJobs && String(args[0]) === '/api/jobs') {
                window.__jobsBodyWaiting = true;
                await new Promise(resolve => { window.__releaseJobs = resolve; });
                window.__jobsBodyReleased = true;
              }
              if (window.__holdPoll && String(args[0]) === '/api/job/fixture-job') {
                window.__pollBodyWaiting = true;
                await new Promise(resolve => { window.__releasePoll = resolve; });
              }
              return payload;
            };
            return response;
          };
        })();""")
        try:
            page.goto(f"{ORIGIN}/tdash.html")
            page.wait_for_function("() => document.querySelector('#dataset-select').options.length > 0"
                                   " && !document.querySelector('#theme-toggle').disabled")
            page.eval_on_selector("#chk-only-cache", """element => {
                element.checked = true;
                element.dispatchEvent(new Event('change', {bubbles: true}));
            }""")
            state.choose()
            assert not any(path.startswith("/api/data/") for path, _, _ in state.requests)
            yield state
            assert state.errors == [], state.errors
            unexpected = [(case, status, url) for case, status, url in state.responses
                          if not (status in {200, 304}
                                  or status == 202 and case["mode"] == "async"
                                  and url.endswith("/api/data/td-otbr-cli-meshdiag-topology.json")
                                  or status == 503 and case["mode"] == "error"
                                  and url.endswith("/api/data/td-otbr-cli-meshdiag-topology.json"))]
            assert unexpected == [], unexpected
        finally:
            failed = getattr(request.node, "rep_call", None)
            if failed is not None and failed.failed or state.errors:
                request.session.browser_failed = True
                artifacts = ROOT / ".pytest-browser-artifacts" / request.node.name
                artifacts.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(artifacts / "failure.png"), full_page=True)
                (artifacts / "events.json").write_text(json.dumps({
                    "case": state.active, "errors": state.errors, "responses": state.responses,
                    "warnings": state.warnings,
                    "requests": state.requests,
                }, indent=2))
                context.tracing.stop(path=str(artifacts / "trace.zip"))
            else:
                context.tracing.stop()
            context.close()
            browser.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)
