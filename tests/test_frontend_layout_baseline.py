from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
HTML = REPO_ROOT / "src" / "tdash.html"
CSS = REPO_ROOT / "src" / "tdash.css"
UI_JS = REPO_ROOT / "src" / "js" / "tdash-ui.js"
UTILS_JS = REPO_ROOT / "src" / "js" / "tdash-utils.js"
DATASET_JS = REPO_ROOT / "src" / "js" / "tdash-dataset.js"
PLAN = REPO_ROOT / "plan" / "five-panel-responsive-layout-draft.md"

BEHAVIOR_IDS = (
    "panel-title",
    "panel-navigation",
    "panel-functions",
    "panel-workspace",
    "panel-device-details",
    "panel-home",
    "device-status",
    "panel-dataset",
    "panel-node-link-filters",
    "panel-view",
    "btn-functions-panel-toggle",
    "btn-more-info",
    "btn-topology",
    "btn-table",
    "btn-insights",
    "btn-settings",
    "btn-logs",
    "view-topology",
    "view-table",
    "view-insights",
    "view-settings",
    "view-logs",
    "device-details",
    "btn-details-panel-toggle",
    "chk-auto-view",
    "datasource-filter",
    "dataset-select",
    "search-input",
    "node-filter",
    "link-filter",
    "diagnostic-source-filter",
    "diagnostic-filter",
)

TARGET_LAYOUT_PANEL_IDS = (
    "panel-title",
    "panel-navigation",
    "panel-functions",
    "panel-workspace",
    "panel-device-details",
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class _IdParentParser(HTMLParser):
    _VOID_ELEMENTS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, str | None]] = []
        self.parent_by_id: dict[str, str | None] = {}
        self.tag_by_id: dict[str, str] = {}
        self.id_order: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element_id = dict(attrs).get("id")
        parent_id = next(
            (ancestor_id for _, ancestor_id in reversed(self.stack) if ancestor_id),
            None,
        )
        if element_id:
            self.parent_by_id[element_id] = parent_id
            self.tag_by_id[element_id] = tag
            self.id_order.append(element_id)
        if tag not in self._VOID_ELEMENTS:
            self.stack.append((tag, element_id))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return


def test_behavior_bearing_dom_ids_exist_once() -> None:
    html = _read_text(HTML)
    id_counts = Counter(re.findall(r'\bid="([^"]+)"', html))

    duplicates = sorted(element_id for element_id, count in id_counts.items() if count > 1)
    assert duplicates == []
    assert {element_id: id_counts[element_id] for element_id in BEHAVIOR_IDS} == {
        element_id: 1 for element_id in BEHAVIOR_IDS
    }


def test_approved_target_layout_panel_ids_are_documented_and_present() -> None:
    plan = _read_text(PLAN)
    html = _read_text(HTML)

    for panel_id in TARGET_LAYOUT_PANEL_IDS:
        assert f'id="{panel_id}"' in plan
        assert f'id="{panel_id}"' in html


def test_semantic_layout_and_workspace_hierarchy() -> None:
    parser = _IdParentParser()
    parser.feed(_read_text(HTML))

    assert parser.tag_by_id["panel-title"] == "header"
    assert parser.tag_by_id["panel-navigation"] == "nav"
    assert parser.tag_by_id["panel-functions"] == "aside"
    assert parser.tag_by_id["panel-workspace"] == "main"
    assert parser.tag_by_id["panel-device-details"] == "aside"
    assert [
        panel_id for panel_id in parser.id_order if panel_id in TARGET_LAYOUT_PANEL_IDS
    ] == [
        "panel-title",
        "panel-functions",
        "panel-workspace",
        "panel-device-details",
        "panel-navigation",
    ]
    assert parser.parent_by_id["panel-home"] == "panel-title"
    assert parser.parent_by_id["device-status"] == "panel-functions"
    assert parser.parent_by_id["panel-view"] == "panel-workspace"
    assert parser.parent_by_id["view-topology"] == "panel-view"
    assert parser.parent_by_id["view-table"] == "panel-view"
    assert parser.parent_by_id["view-insights"] == "panel-view"
    assert parser.parent_by_id["view-settings"] == "panel-view"
    assert parser.parent_by_id["view-logs"] == "panel-view"
    assert parser.parent_by_id["btn-more-info"] == "panel-view"
    assert parser.parent_by_id["chk-auto-view"] == "overview-settings-section"
    assert parser.parent_by_id["device-details"] == "panel-device-details"
    assert parser.parent_by_id["topology-view"] == "view-topology"


def test_workspace_switch_registry_owns_all_five_views() -> None:
    ui_text = _read_text(UI_JS)
    registry_start = ui_text.index("const WORKSPACE_VIEWS")
    switch_end = ui_text.index("// ── Physics toggle", registry_start)
    switch_source = ui_text[registry_start:switch_end]

    for view in ("topology", "table", "insights", "settings", "logs"):
        assert f'view: "{view}"' in switch_source
    assert "panelEl.hidden = !isActive;" in switch_source
    assert 'buttonEl.setAttribute("aria-selected", String(isActive));' in switch_source
    assert "buttonEl.tabIndex = isActive ? 0 : -1;" in switch_source
    assert "WORKSPACE_VIEWS.forEach(({ view, buttonId }, index)" in switch_source
    assert 'const navigationKeys = ["ArrowLeft", "ArrowRight", "Home", "End"];' in switch_source


def test_workspace_lifecycle_and_activity_contract() -> None:
    ui_text = _read_text(UI_JS)
    dataset_text = _read_text(DATASET_JS)

    assert "const lastRenderedDatasetByView = new Map();" in ui_text
    assert "lastRenderedDatasetByView.get(view) === currentDataset" in ui_text
    assert "rendersDataset: true" in ui_text
    assert "onActivate: resizeAndFitTopology" in ui_text
    assert "network.setSize" in ui_text
    assert "network.redraw();" in ui_text
    assert "handleDetailsPanelVisibilityChanged" in ui_text
    assert 'classList.toggle(\n    "details-panel-collapsed"' in ui_text
    assert "setFunctionsPanelCollapsed" in ui_text
    assert '"functions-panel-collapsed"' in ui_text
    assert "WORKSPACE_ACTIVITY_LIMIT = 100" in ui_text
    assert "workspaceActivity.splice" in ui_text
    assert "setDatasetActivityObserver" in ui_text
    assert 'userInitiated: true' in ui_text
    assert '["topology", "table"].includes(selectedDataset?.defaultView)' in ui_text
    assert "export function setDatasetActivityObserver" in dataset_text
    assert '"api-response"' in dataset_text
    assert '"job-status"' in dataset_text
    assert "response.json()" in dataset_text
    assert "response.headers" not in ui_text[ui_text.index("function renderWorkspaceLogs"):ui_text.index("export function getSearchQuery")]


def test_details_collapse_targets_explicit_details_owner_and_notifies_renderer() -> None:
    utils_text = _read_text(UTILS_JS)
    toggle_start = utils_text.index("export function initDetailPanelToggles")
    toggle_end = utils_text.index("headings.forEach", toggle_start)
    toggle_source = utils_text[toggle_start:toggle_end]

    assert 'panelEl.closest("#panel-device-details")' in toggle_source
    assert 'panelDetailsEl?.classList.toggle("details-panel-collapsed"' in toggle_source
    assert 'panelEl.classList.toggle("details-panel-collapsed"' in toggle_source
    assert "onPanelVisibilityChanged?.(isPanelCollapsed);" in toggle_source
    assert 'btn.textContent = collapsed ? "◀" : "▶";' in toggle_source


def test_vis_navigation_rules_are_not_nested_under_unused_heading() -> None:
    css = _read_text(CSS)

    assert re.search(r"h1\s*\{[^}]*div\.vis-network", css, re.DOTALL) is None


def test_responsive_dashboard_grid_contract() -> None:
    css = _read_text(CSS)

    assert '"title"\n    "functions"\n    "workspace"\n    "details"\n    "navigation"' in css
    assert "@media (min-width: 721px)" in css
    assert '"functions workspace"\n      "navigation details"' in css
    assert "@media (min-width: 1124px)" in css
    assert '"navigation functions workspace details"' in css
    assert ".dashboard-shell.details-panel-collapsed" in css
    assert '"navigation functions workspace"' in css
    assert ".dashboard-shell.functions-panel-collapsed" in css
    assert '"navigation workspace details"' in css
    assert '"navigation workspace"' in css
    assert "grid-template-rows: auto minmax(0, 1fr);" in css
    assert "position: fixed;" in css
    assert "env(safe-area-inset-bottom)" in css
    assert "grid-template-columns: repeat(5, minmax(0, 1fr));" in css
