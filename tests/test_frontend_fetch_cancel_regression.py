from __future__ import annotations

from pathlib import Path
import re
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_JS = REPO_ROOT / "src" / "js" / "tdash-dataset.js"
UI_JS = REPO_ROOT / "src" / "js" / "tdash-ui.js"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_load_dataset_has_stale_session_guards() -> None:
    """Regression guard: stale or cancelled sessions must not update dataset state."""
    text = _read_text(DATASET_JS)

    assert "export async function loadDataset(entryValue, options = {})" in text

    first_guard = text.find("_assertFetchSessionActive(sessionId);")
    current_dataset_set = text.find("currentDataset = {")
    assert first_guard != -1
    assert current_dataset_set != -1
    assert first_guard < current_dataset_set, (
        "loadDataset must validate active session before mutating currentDataset"
    )

    cancelled_block = text.find(
        "const cancelledByResult = [...settled, ...auxiliarySettled].some("
    )
    cancelled_throw = text.find("throw new FetchCancelledError(", cancelled_block)
    assert cancelled_block != -1 and cancelled_throw != -1
    final_dataset_set = text.find("\n  currentDataset = {", cancelled_throw)
    assert final_dataset_set != -1
    assert cancelled_throw < final_dataset_set, (
        "Cancellation detection must happen before committing the final dataset"
    )


def test_failed_repeat_sync_cannot_complete_against_prior_dataset() -> None:
    dataset_text = _read_text(DATASET_JS)
    ui_text = _read_text(UI_JS)

    assert "return currentDataset;" in dataset_text
    assert "currentDataset = acceptedDataset;" in dataset_text
    assert "acceptedDataset;" in dataset_text
    assert "acceptedDataset = currentDataset;" in dataset_text
    assert 'isPartial: failedFiles.length > 0 || materializationStates.includes("partial")' in dataset_text
    assert "if (failedFiles.length === 0) acceptedDataset = currentDataset;" in dataset_text
    assert 'result.status === "fulfilled" && result.value != null' in dataset_text
    assert "loadedDataset = await loadDataset(selectedValue" in ui_text
    assert "if (!loadedDataset || currentDataset !== loadedDataset)" in ui_text
    assert "Still displaying ${datasetIdentityLabel(currentDataset)}." in ui_text
    assert "No dataset is available to display." in ui_text
    assert "function clearRenderedDatasetViews(emptyDataset)" in ui_text
    assert "fetchAttemptVersion" in ui_text
    assert "? sameDataset && refreshIntent" in ui_text
    assert "clearRenderedDatasetViews({" in ui_text
    assert "Number.POSITIVE_INFINITY" in ui_text


def test_completed_job_fetches_the_new_snapshot_without_redispatching() -> None:
    text = _read_text(DATASET_JS)

    completed_fetch = text.find('finalResponse = await trackedFetch(`/api/data/${filename}`')
    cache_header = text.find(
        '"Cache-Control": `only-if-cached, max-age=${_CACHE_ONLY_MAX_AGE_SECONDS}`',
        completed_fetch,
    )
    redispatch_guard = text.find("if (finalResponse.status === 202)", completed_fetch)

    assert completed_fetch != -1
    assert completed_fetch < cache_header < redispatch_guard


def test_partial_baseline_failure_and_success_presentation() -> None:
    result = subprocess.run(
        ["node", "--unhandled-rejections=strict", "--input-type=module", "-e", r"""
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { resolveNetworkInstance, networkInstanceStatus } from "./src/js/tdash-view-status.js";
const source = readFileSync("./src/js/tdash-ui.js", "utf8");
const entry = { value: "partial-test", source: "test", label: "Partial test", files: ["a.json"] };
const baseline = { entry, rows: [{ name: "Retained" }], loadedFiles: entry.files,
  isPartial: true, materializationState: "partial", fetchDurationMs: 42 };
const elements = new Map(), renders = [], activity = [];
const element = (id) => {
  if (!elements.has(id)) elements.set(id, {
    value: id === "dataset-select" ? entry.value : "", checked: false,
    textContent: "", toggleAttribute() {},
  });
  return elements.get(id);
};
let presenter, outcome, cleared = 0, ended = 0;
const context = vm.createContext({
  currentDataset: baseline, currentView: "table", sourceCapabilities: {},
  window: { tdashDebug: {} }, Date, setTimeout, clearTimeout,
  document: { getElementById: element },
  DATASET_REGISTRY: [entry], DATASOURCE_REGISTRY: [{ value: "test", label: "Test" }],
  statusDisclosure: { close() {}, update() {} }, healthInsightsState: {},
  resolveNetworkInstance, networkInstanceStatus,
  configureViewStatusPresenter: (callback) => { presenter = callback; },
  _setStatusSpans() {}, setFetchButtonsState() {},
  startFetchSession: () => 1, endFetchSession: () => { ended++; },
  recordWorkspaceActivity: (...args) => activity.push(args), recordActivity() {},
  switchView() {}, supersedeViewStatus() {}, isFetchCancelledError: () => false,
  loadSourceCapabilities: async () => ({}), setTableColumnCategory() {},
  resetDeviceDetailsPanelTabsToDefault() {}, invalidateHealthRefresh() {},
  refreshHealthAssessment: async () => {}, updateFetchStatusBar() {},
  clearRenderedDatasetViews: () => { cleared++; },
  restoreLastKnownGoodDataset: () => { context.currentDataset = baseline; return baseline; },
  console: { error() {}, warn() {} },
  _pinFetchStatusLineMessage: (message) => {
    element("fetch-status-line-content").textContent = message;
    context.window.tdashDebug.fetchStatusPinnedUntil = Infinity;
  },
  renderCurrentView: () => {
    renders.push(context.currentDataset);
    presenter({ summary: "Ready", details: [], state: "ready" });
  },
  loadDataset: async () => {
    if (outcome === "throw") {
      context.currentDataset = { ...baseline, rows: [] };
      throw new Error("Assembly failed");
    }
    if (outcome === "missing") {
      context.currentDataset = baseline;
      element("fetch-status-line-content").textContent = "Required file unavailable";
      return null;
    }
    context.currentDataset = { ...baseline, isPartial: outcome === "partial",
      materializationState: outcome === "partial" ? "partial" : "complete" };
    return context.currentDataset;
  },
});
const identity = source.slice(source.indexOf("function datasetIdentityLabel("),
  source.indexOf("function createStatusDisclosure("));
const presentation = source.slice(source.indexOf("configureViewStatusPresenter((status) => {"),
  source.indexOf("// ── Build datasource"));
const errorHandler = source.slice(source.indexOf("function handleDatasetFetchError("),
  source.indexOf("// Fetch dataset function"));
const fetchOwner = source.slice(source.indexOf("async function doFetchDataset("),
  source.indexOf("// Fetch button drives data acquisition."));
vm.runInContext(`
  let fetchFailureState = null, statusContext = null, _fetchInProgress = false;
  let fetchAttemptVersion = 0, _lastFetchStartedAt = 0, _currentSearchQuery = "";
  const _FETCH_STATUS_IDS = [], _DEVICE_STATUS_IDS = [];
  ${identity}
  ${presentation}
  ${errorHandler}
  ${fetchOwner}
  globalThis.api = { sync: doFetchDataset, failure: () => fetchFailureState };
`, context);
for (outcome of ["missing", "throw"]) {
  await context.api.sync();
  assert.equal(context.currentDataset, baseline);
  assert.equal(renders.at(-1), baseline);
  assert.match(context.api.failure(), /failed|Could not load/i);
  for (const view of ["topology", "table"]) {
    context.currentView = view;
    context.renderCurrentView();
    assert.match(element("view-status-line-content").textContent, /Incomplete preview/);
    assert.match(element("view-status-line-content").textContent, /Sync failed; retained data/);
  }
}
outcome = "partial";
await context.api.sync();
assert.equal(context.api.failure(), null);
assert.match(element("fetch-status-line-content").textContent, /Incomplete Unified dataset/);
assert.match(element("view-status-line-content").textContent, /Incomplete preview/);
assert.doesNotMatch(element("view-status-line-content").textContent, /Sync failed/);
outcome = "complete";
await context.api.sync();
assert.equal(context.api.failure(), null);
assert.doesNotMatch(element("view-status-line-content").textContent, /Incomplete|Sync failed/);
assert.equal(cleared, 0);
assert.equal(ended, 4);
assert.ok(activity.some((event) => event[1] === "Dataset sync produced no usable data"));
assert.ok(activity.some((event) => event[1] === "Dataset sync failed"));
assert.ok(activity.some((event) => event[1] === "Dataset sync incomplete"));
assert.ok(activity.some((event) => event[1] === "Dataset sync completed"));
"""],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_shift_sync_uses_the_direct_refresh_request_intent() -> None:
    ui_text = _read_text(UI_JS)
    dataset_text = _read_text(DATASET_JS)

    assert "async function doFetchDataset({ userInitiated = false, forceFresh = false } = {})" in ui_text
    assert "forceFresh: event.shiftKey" in ui_text
    assert "forceFresh," in ui_text
    assert "const forceFresh = options.forceFresh === true;" in dataset_text
    assert "_datasetRequestHeaders(f, forceFresh)" in dataset_text
    assert "_datasetRequestHeaders(filename, forceFresh)" in dataset_text
    assert "forceFresh || _forceFresh" in dataset_text



def test_ui_cancel_path_keeps_current_view_on_cancellation() -> None:
    """Regression guard: cancellation must keep existing rendered view (no partial overwrite)."""
    text = _read_text(UI_JS)

    assert "if (isFetchCancelledError(err))" in text
    assert "statusEl.textContent = `Fetch cancelled for \"${selectedValue}\".`;" in text

    cancellation = text.split("function handleDatasetFetchCancellation(", 1)[1].split(
        "function handleDatasetFetchError(", 1
    )[0]
    assert "resetFetchTimeTakenProgressToDefault();" in cancellation
    assert "if (currentDataset) {" in cancellation
    assert "renderCurrentView();" in cancellation
    assert "updateFetchStatusBar(fetchStartedAt);" in cancellation
    assert "_setStatusSpans(_FETCH_STATUS_IDS, \"—\");" in cancellation
    assert "currentDataset.isPartial === true" in cancellation
    assert "activateViewStatus(currentView, currentDataset);" in cancellation


def test_fetch_attempt_owns_cleanup_and_distinct_no_result_transition() -> None:
    text = _read_text(UI_JS)
    owner = text.split("async function doFetchDataset(", 1)[1]
    catch_transition = owner.split("} catch (err) {", 1)[1].split("} finally {", 1)[0]
    cleanup = owner.split("} finally {", 1)[1].split(
        "if (!loadedDataset || currentDataset !== loadedDataset)", 1
    )[0]

    assert "clearTimeout(_incrementalRenderTimer)" in catch_transition
    assert "handleDatasetFetchCancellation(selectedValue, _lastFetchStartedAt)" in catch_transition
    assert "handleDatasetFetchError(err, selectedValue, selectedDataset, refreshIntent, _lastFetchStartedAt)" in catch_transition
    assert "await " not in catch_transition
    assert "return;" in catch_transition
    assert "endFetchSession(sessionId)" in cleanup
    assert "_fetchInProgress = false" in cleanup
    assert "setFetchButtonsState(false)" in cleanup
    no_result = owner.split(
        "if (!loadedDataset || currentDataset !== loadedDataset)", 1
    )[1].split("// Cancel any pending incremental render", 1)[0]
    assert "failureDetails" in no_result
    assert "Dataset sync produced no usable data" in no_result
    assert "handleDatasetFetchError(" not in no_result
    for helper in ("handleDatasetFetchCancellation", "handleDatasetFetchError"):
        assert not re.search(rf"(?:async|export)\s+function\s+{helper}\b", text)


def test_ui_cancel_path_resets_progress_to_default() -> None:
    """Regression guard: cancellation should restore progress element default state."""
    text = _read_text(UI_JS)

    assert "function resetFetchTimeTakenProgressToDefault()" in text
    assert "progressEl.removeAttribute(\"value\");" in text
