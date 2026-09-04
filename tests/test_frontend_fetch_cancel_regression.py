from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_JS = REPO_ROOT / "src" / "js" / "tdash-dataset.js"
UI_JS = REPO_ROOT / "src" / "js" / "tdash-ui.js"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_cancel_all_active_jobs_for_current_fetch_session() -> None:
    """Regression guard: cancel flow must fan out DELETE to all tracked job IDs."""
    text = _read_text(DATASET_JS)

    assert "export async function cancelActiveFetchSession()" in text
    assert "const jobIds = Array.from(_activeFetchSession.activeJobIds);" in text
    assert "jobIds.map((jobId) => fetch(`/api/job/${jobId}`, { method: \"DELETE\" }))" in text



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

    cancelled_block = text.find("const cancelledByResult = settled.some(")
    cancelled_throw = text.find("throw new FetchCancelledError(", cancelled_block)
    assert cancelled_block != -1 and cancelled_throw != -1
    assert cancelled_throw < current_dataset_set, (
        "Cancellation detection must happen before currentDataset assignment"
    )


def test_completed_job_fetches_the_new_snapshot_without_redispatching() -> None:
    text = _read_text(DATASET_JS)

    completed_fetch = text.find('finalResponse = await fetch(`/api/data/${filename}`')
    cache_header = text.find(
        '"Cache-Control": `max-age=${_CACHE_ONLY_MAX_AGE_SECONDS}`',
        completed_fetch,
    )
    redispatch_guard = text.find("if (finalResponse.status === 202)", completed_fetch)

    assert completed_fetch != -1
    assert completed_fetch < cache_header < redispatch_guard



def test_ui_cancel_path_keeps_current_view_on_cancellation() -> None:
    """Regression guard: cancellation must keep existing rendered view (no partial overwrite)."""
    text = _read_text(UI_JS)

    assert "if (isFetchCancelledError(err))" in text
    assert "statusEl.textContent = `Fetch cancelled for \"${selectedValue}\".`;" in text

    cancelled_branch_start = text.find("if (isFetchCancelledError(err))")
    cancelled_branch_end = text.find("return;", cancelled_branch_start)
    assert cancelled_branch_start != -1 and cancelled_branch_end != -1

    cancelled_branch = text[cancelled_branch_start:cancelled_branch_end]
    assert "resetFetchTimeTakenProgressToDefault();" in cancelled_branch
    assert "if (currentDataset) {" in cancelled_branch
    assert "renderCurrentView();" in cancelled_branch
    assert "updateFetchStatusBar(_lastFetchStartedAt);" in cancelled_branch
    assert "_setStatusSpans(_FETCH_STATUS_IDS, \"—\");" in cancelled_branch


def test_ui_cancel_path_resets_progress_to_default() -> None:
    """Regression guard: cancellation should restore progress element default state."""
    text = _read_text(UI_JS)

    assert "function resetFetchTimeTakenProgressToDefault()" in text
    assert "progressEl.removeAttribute(\"value\");" in text
