from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[1]
HTML = REPO_ROOT / "src" / "tdash.html"
CSS = REPO_ROOT / "src" / "tdash.css"
UI_JS = REPO_ROOT / "src" / "js" / "tdash-ui.js"
UTILS_JS = REPO_ROOT / "src" / "js" / "tdash-utils.js"
DATASET_JS = REPO_ROOT / "src" / "js" / "tdash-dataset.js"

BEHAVIOR_IDS = (
    "panel-title",
    "panel-navigation",
    "btn-navigation-panel-toggle",
    "panel-functions",
    "panel-workspace",
    "panel-context-details",
    "health-finding-details",
    "panel-home",
    "device-status",
    "btn-device-status-close",
    "panel-dataset",
    "panel-node-link-filters",
    "panel-view",
    "btn-functions-panel-toggle",
    "btn-more-info",
    "btn-topology",
    "btn-table",
    "btn-insights",
    "btn-settings",
    "btn-operations",
    "view-topology",
    "topology-title",
    "topology-canvas-wrap",
    "topology-toolbar-row",
    "topology-controls",
    "lq-legend",
    "view-table",
    "view-insights",
    "health-insights-workspace",
    "health-insights-summary",
    "health-insights-navigation",
    "health-insights-tabs",
    "health-findings-count",
    "health-roster-count",
    "health-tab-findings",
    "health-tab-comparison",
    "health-tab-roster",
    "health-panel-findings",
    "health-panel-comparison",
    "health-panel-roster",
    "view-settings",
    "view-operations",
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
    "panel-context-details",
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
        self.stack: list[tuple[str, str | None, frozenset[str]]] = []
        self.parent_by_id: dict[str, str | None] = {}
        self.tag_by_id: dict[str, str] = {}
        self.attributes_by_id: dict[str, dict[str, str | None]] = {}
        self.inside_dashboard_shell_by_id: dict[str, bool] = {}
        self.inside_health_insights_sticky_by_id: dict[str, bool] = {}
        self.inside_health_insights_workspace_by_id: dict[str, bool] = {}
        self.id_order: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        element_id = attributes.get("id")
        classes = frozenset((attributes.get("class") or "").split())
        parent_id = next(
            (ancestor_id for _, ancestor_id, _ in reversed(self.stack) if ancestor_id),
            None,
        )
        if element_id:
            self.parent_by_id[element_id] = parent_id
            self.tag_by_id[element_id] = tag
            self.attributes_by_id[element_id] = attributes
            self.inside_dashboard_shell_by_id[element_id] = any(
                "dashboard-shell" in ancestor_classes
                for _, _, ancestor_classes in self.stack
            )
            self.inside_health_insights_sticky_by_id[element_id] = any(
                "health-insights-sticky" in ancestor_classes
                for _, _, ancestor_classes in self.stack
            )
            self.inside_health_insights_workspace_by_id[element_id] = any(
                ancestor_id == "health-insights-workspace"
                for _, ancestor_id, _ in self.stack
            )
            self.id_order.append(element_id)
        if tag not in self._VOID_ELEMENTS:
            self.stack.append((tag, element_id, classes))

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


def test_approved_target_layout_panel_ids_are_present() -> None:
    html = _read_text(HTML)

    for panel_id in TARGET_LAYOUT_PANEL_IDS:
        assert f'id="{panel_id}"' in html


def test_appearance_bootstrap_and_controls() -> None:
    html = _read_text(HTML)
    parser = _IdParentParser()
    parser.feed(html)
    assert html.index('src="js/tdash-theme.js"') < html.index('src="js/depend/vis-network.min.js"')
    assert html.index('src="js/tdash-theme.js"') < html.index('href="tdash.css"')
    assert parser.parent_by_id["header-appearance"] == "panel-title"
    for control in ("theme-toggle", "settings-theme-toggle"):
        assert parser.tag_by_id[control] == "button"
        assert parser.attributes_by_id[control]["type"] == "button"
        assert "disabled" in parser.attributes_by_id[control]
        assert parser.attributes_by_id[control]["aria-label"] == "Theme: System"
        assert parser.attributes_by_id[control]["title"] == "Theme: System (follows device appearance)"
        assert "aria-pressed" not in parser.attributes_by_id[control]
    assert "<span>Theme</span>" not in html
    assert html.count('class="theme-toggle-icon" aria-hidden="true">&#9681;') == 2
    assert 'id="theme-select"' not in html
    assert 'id="settings-theme-select"' not in html
    assert parser.attributes_by_id["theme-status"]["role"] == "status"
    assert "role" not in parser.attributes_by_id["settings-theme-status"]
    css = _read_text(CSS)
    assert ':root[data-theme="dark"]' in css
    assert ':root:not([data-theme])' in css
    assert ".appearance-controls" in css


def test_dashboard_control_icons_are_theme_aware_and_decorative() -> None:
    html = _read_text(HTML)
    parser = _IdParentParser()
    parser.feed(html)
    for button_id, icon_class in (
        ("btn-topology", "topology-icon"),
        ("btn-insights", "insights-icon"),
        ("btn-device-details-insights", "insights-icon"),
        ("btn-device-details-properties", "properties-icon"),
        ("btn-operations", "operations-icon"),
        ("btn-fetch-toggle-status-chk-cache", "disclosure-icon"),
        ("btn-toggle-node-diag-filters", "disclosure-icon"),
    ):
        button = re.search(rf'<button id="{button_id}".*?</button>', html, re.DOTALL)
        assert button is not None
        assert icon_class in button[0]
        assert 'stroke="currentColor"' in button[0]
        assert 'aria-hidden="true" focusable="false"' in button[0]
        assert all(emoji not in button[0] for emoji in ("🌐", "💡", "⧨", "🔭", "📋"))
        if icon_class == "topology-icon":
            assert 'width="20" height="20"' in button[0]
            assert 'fill="none" stroke="currentColor" stroke-width="1.8"' in button[0]
            assert button[0].count("<circle ") == 6
            assert 'M12 3v18"' in button[0]
            assert 'M20 7.5l-16 9' in button[0]
            assert 'Zm-8 4.5 16 9' in button[0]
            assert 'fill="currentColor" stroke="none"' in button[0]
        if icon_class in ("properties-icon", "operations-icon"):
            assert 'width="20" height="20"' in button[0]
            assert 'fill="none" stroke="currentColor" stroke-width="1.8"' in button[0]
            assert button[0].count("<rect ") == (1 if icon_class == "properties-icon" else 2)
    for button_id, label in (
        ("btn-topology", "Topology view"),
        ("btn-device-details-properties", "Show device properties"),
        ("btn-operations", "Operations view"),
    ):
        assert parser.attributes_by_id[button_id]["aria-label"] == label
        assert parser.attributes_by_id[button_id]["title"] == label
    for button_id, targets in (
        ("btn-fetch-toggle-status-chk-cache", "fieldset-cache"),
        ("btn-toggle-node-diag-filters", "fieldset-node-link-filters fieldset-diag-filters"),
    ):
        attributes = parser.attributes_by_id[button_id]
        assert attributes["type"] == "button"
        assert attributes["aria-expanded"] == "false"
        assert attributes["aria-controls"] == targets
        assert attributes["aria-label"].startswith("Show ")
    assert 'button[aria-expanded="true"] > .disclosure-icon' in _read_text(CSS)


def test_links_status_uses_decorative_signal_bars_and_preserves_count() -> None:
    html = _read_text(HTML)
    parser = _IdParentParser()
    parser.feed(html)
    assert parser.tag_by_id["device-status-links"] == "span"
    assert parser.parent_by_id["link-count"] == "device-status-links"
    assert "role" not in parser.attributes_by_id["device-status-links"]
    icon = re.search(r'<svg class="links-signal-icon".*?</svg>', html, re.DOTALL)
    assert icon is not None
    for attribute in (
        'width="18" height="18"', 'fill="currentColor"',
        'aria-hidden="true" focusable="false"',
    ):
        assert attribute in icon[0]
    assert re.findall(r'<rect .*?height="(\d+)" rx="1"', icon[0]) == ["5", "9", "14", "18"]
    assert '<span>Links: <span id="link-count">0</span></span>' in html
    for quality in ("lq3", "lq2", "lq1"):
        assert parser.parent_by_id[f"{quality}-count"] == f"device-status-{quality}"


def test_fieldset_disclosures_follow_individual_and_grouped_visibility() -> None:
    script = r"""
      import assert from "node:assert/strict";
      import fs from "node:fs";
      import vm from "node:vm";
      const elements = new Map();
      const containers = {
        "btn-toggle-cache": "fieldset-cache",
        "btn-toggle-node-link-filters": "fieldset-node-link-filters",
        "btn-toggle-diag-filters": "fieldset-diag-filters",
      };
      function element(id) {
        if (!elements.has(id)) {
          const classes = new Set();
          const attrs = new Map([["aria-expanded", "false"]]);
          const listeners = new Map();
          elements.set(id, {
            hidden: id.startsWith("fieldset-"),
            classList: {
              contains: name => classes.has(name),
              add: name => classes.add(name),
              remove: name => classes.delete(name),
              toggle: name => classes.has(name) ? classes.delete(name) : classes.add(name),
            },
            setAttribute: (key, value) => attrs.set(key, value),
            getAttribute: key => attrs.get(key),
            closest: () => element(containers[id]),
            addEventListener: (name, callback) => listeners.set(name, callback),
            click: () => listeners.get("click")(),
          });
        }
        return elements.get(id);
      }
      const ui = fs.readFileSync("src/js/tdash-ui.js", "utf8");
      const start = ui.indexOf("const COLLAPSE_CONTAINER_BY_BUTTON_ID");
      const end = ui.indexOf("// ── Collapsible Filters Panel", start);
      assert.ok(start >= 0 && end > start);
      vm.runInNewContext(ui.slice(start, end), {document: {getElementById: element}});
      const cache = element("btn-fetch-toggle-status-chk-cache");
      const filters = element("btn-toggle-node-diag-filters");
      const expanded = (button, expected, label) => {
        assert.equal(button.getAttribute("aria-expanded"), String(expected));
        assert.equal(button.getAttribute("aria-label"), `${expected ? "Hide" : "Show"} ${label}`);
        assert.equal(button.title, button.getAttribute("aria-label"));
      };
      expanded(cache, false, "cache options");
      expanded(filters, false, "node, link and diagnostic filters");
      cache.click();
      expanded(cache, true, "cache options");
      assert.equal(element("fieldset-cache").hidden, false);
      element("btn-toggle-cache").click();
      expanded(cache, false, "cache options");
      cache.click();
      expanded(cache, true, "cache options");
      assert.equal(element("fieldset-cache").classList.contains("collapsed"), false);
      cache.click();
      expanded(cache, false, "cache options");
      assert.equal(element("fieldset-cache").hidden, true);
      filters.click();
      expanded(filters, true, "node, link and diagnostic filters");
      for (const header of ["btn-toggle-node-link-filters", "btn-toggle-diag-filters"]) {
        element(header).click();
        expanded(filters, false, "node, link and diagnostic filters");
        filters.click();
        expanded(filters, true, "node, link and diagnostic filters");
        assert.equal(element(containers[header]).classList.contains("collapsed"), false);
      }
      element("btn-toggle-diag-filters").click();
      element("btn-toggle-diag-filters").click();
      expanded(filters, true, "node, link and diagnostic filters");
      filters.click();
      expanded(filters, false, "node, link and diagnostic filters");
      assert.equal(element("fieldset-node-link-filters").hidden, true);
      assert.equal(element("fieldset-diag-filters").hidden, true);
      expanded(cache, false, "cache options");
    """
    subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_header_theme_toggle_matches_compact_panel_close_size() -> None:
    css = _read_text(CSS)
    header = re.search(r"#theme-toggle\s*\{([^}]+)\}", css)
    assert header is not None
    for declaration in ("min-width: 0;", "min-height: 0;", "width: 36px;", "height: 30px;", "padding: 0;"):
        assert declaration in header[1]
    icon = re.search(r"#theme-toggle \.theme-toggle-icon\s*\{([^}]+)\}", css)
    assert icon is not None
    assert "font-size: 14px;" in icon[1]
    shared = re.search(r"\.theme-toggle\s*\{([^}]+)\}", css)
    assert shared is not None
    assert "min-width: 44px;" in shared[1]
    assert "min-height: 44px;" in shared[1]


def test_appearance_palette_contrast_and_fallback_parity() -> None:
    css = _read_text(CSS)

    def tokens(selector: str) -> dict[str, str]:
        block = re.search(re.escape(selector) + r"\s*\{([^}]+)\}", css)
        assert block is not None
        return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", block[1]))

    light = tokens(":root")
    dark = tokens(':root[data-theme="dark"]')
    assert tokens(":root:not([data-theme])") == dark
    assert {key: dark[key] for key in (
        "--dashboard-panel-bg", "--dashboard-group-divider",
        "--dashboard-canvas-border", "--dashboard-supporting-text",
    )} == {
        "--dashboard-panel-bg": "#171a1d",
        "--dashboard-group-divider": "#2a3036",
        "--dashboard-canvas-border": "#252b31",
        "--dashboard-supporting-text": "#adb7c5",
    }
    assert css.count("--dashboard-panel-border: transparent;") == 2
    assert "--dashboard-panel-bg: var(--surface-raised);" in css
    assert "--dashboard-panel-border: var(--line);" in css
    assert light["--topology-canvas-bg"] == "#ffffff"
    assert dark["--topology-canvas-bg"] == "#121416"
    assert {key: dark[key] for key in (
        "--bg", "--surface", "--surface-raised", "--surface-stripe",
        "--topology-label-bg", "--topology-search-dim-bg",
    )} == {
        "--bg": "#121416",
        "--surface": "#1c2024",
        "--surface-raised": "#181b1e",
        "--surface-stripe": "#22272b",
        "--topology-label-bg": "#171a1d",
        "--topology-search-dim-bg": "#252a2f",
    }
    canvas_rules = re.search(r"#topology-view\s*\{([^}]+)\}", css)
    assert canvas_rules is not None
    assert "background: var(--topology-canvas-bg);" in canvas_rules[1]
    approved_roles = {
        "router": ("#dcecf8", "#4b4237", "#18354f", "#f2ede3"),
        "border-router": ("#e4f3e7", "#28723a", "#153923", "#70c982"),
        "reed": ("#c2d9fa", "#24559a", "#24559a", "#91baff"),
        "med": ("#c8f0f5", "#006b80", "#104655", "#62d6ed"),
        "sed": ("#ffffff", "#006b80", "#121416", "#62d6ed"),
        "child": ("#fff0c2", "#806000", "#3c3218", "#e8c766"),
        "eve": ("#ddf2ef", "#006b6b", "#143d3d", "#6acaca"),
        "unknown": ("#e7ebf0", "#5d6672", "#303844", "#b4becc"),
    }
    for role, expected in approved_roles.items():
        assert (
            light[f"--node-{role}-bg"], light[f"--node-{role}-border"],
            dark[f"--node-{role}-bg"], dark[f"--node-{role}-border"],
        ) == expected
    approved_edges = {
        "high": ("#4e8afa", "#4e8afa"),
        "medium": ("#30343b", "#e5ad55"),
        "low": ("#b43b24", "#f18e79"),
        "none": ("#626c7a", "#adb7c5"),
        "parent-child": ("#934e86", "#d69cc9"),
        "otbr": ("#00766a", "#65c9b8"),
    }
    for quality, expected in approved_edges.items():
        assert (light[f"--lq-{quality}"], dark[f"--lq-{quality}"]) == expected

    def luminance(value: str) -> float:
        rgb = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
            for channel in rgb
        ]
        return sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    for palette in (light, light | dark):
        pairs = [
            ("--text", "--surface", 4.5),
            ("--muted", "--surface-stripe", 4.5),
            ("--action-text", "--action-bg", 4.5),
            ("--action-bg", "--surface", 3),
            ("--text-on-selected", "--surface-selected", 4.5),
            ("--text-heading", "--accent-soft", 4.5),
            ("--topology-label-text", "--topology-label-bg", 4.5),
            ("--topology-search-dim-text", "--topology-search-dim-bg", 4.5),
            ("--control-border", "--surface", 3),
            ("--focus-ring", "--surface", 3),
        ]
        for background in ("--bg", "--surface", "--surface-raised", "--surface-stripe"):
            pairs.append(("--text", background, 4.5))
            pairs.append(("--muted", background, 4.5))
            pairs.append(("--control-border", background, 3))
        for role in approved_roles:
            pairs.append((f"--node-{role}-border", f"--node-{role}-bg", 3))
            pairs.append((f"--node-{role}-border", "--surface", 3))
            pairs.append((f"--node-{role}-border", "--topology-canvas-bg", 3))
        pairs.append(("--lq-high", "--surface", 3))
        pairs.append(("--lq-high", "--topology-canvas-bg", 3))
        for quality in ("medium", "low", "none", "parent-child", "otbr"):
            pairs.append((f"--lq-{quality}", "--surface", 4.5))
            pairs.append((f"--lq-{quality}", "--topology-canvas-bg", 4.5))
        for status in ("poor", "moderate", "strong", "unknown"):
            pairs.append((f"--health-{status}", f"--health-{status}-bg", 4.5))
            pairs.append((f"--health-{status}", "--surface", 4.5))
        if "--dashboard-panel-bg" in palette:
            pairs.extend([
                ("--dashboard-supporting-text", "--dashboard-panel-bg", 4.5),
                ("--text", "--dashboard-panel-bg", 4.5),
                ("--control-border", "--dashboard-panel-bg", 3),
                ("--focus-ring", "--dashboard-panel-bg", 3),
            ])
        for foreground, background, threshold in pairs:
            values = sorted((luminance(palette[foreground]), luminance(palette[background])))
            assert (values[1] + 0.05) / (values[0] + 0.05) >= threshold, (foreground, background)
    assert "transition: background" not in css
    high_label = re.search(r"\.lq-high\s*\{([^}]+)\}", css)
    assert high_label is not None
    assert "color: var(--text);" in high_label[1]
    thread_headers = re.search(r"\.thread-network-table th\s*\{([^}]+)\}", css)
    assert thread_headers is not None
    assert "color:" not in thread_headers[1]


def test_semantic_layout_and_workspace_hierarchy() -> None:
    parser = _IdParentParser()
    parser.feed(_read_text(HTML))

    assert parser.tag_by_id["panel-title"] == "header"
    assert parser.tag_by_id["panel-navigation"] == "nav"
    assert parser.tag_by_id["panel-functions"] == "aside"
    assert parser.tag_by_id["panel-workspace"] == "main"
    assert parser.tag_by_id["panel-context-details"] == "aside"
    assert all(
        parser.inside_dashboard_shell_by_id[panel_id]
        for panel_id in TARGET_LAYOUT_PANEL_IDS
    )
    assert [
        panel_id for panel_id in parser.id_order if panel_id in TARGET_LAYOUT_PANEL_IDS
    ] == [
        "panel-title",
        "panel-functions",
        "panel-workspace",
        "panel-context-details",
        "panel-navigation",
    ]
    assert parser.parent_by_id["panel-home"] == "panel-title"
    assert parser.parent_by_id["device-status"] == "panel-functions"
    assert parser.parent_by_id["panel-view"] == "panel-workspace"
    assert parser.parent_by_id["view-topology"] == "panel-view"
    assert parser.parent_by_id["view-table"] == "panel-view"
    assert parser.parent_by_id["view-insights"] == "panel-view"
    assert parser.parent_by_id["view-settings"] == "panel-view"
    assert parser.parent_by_id["view-operations"] == "panel-view"
    assert parser.parent_by_id["btn-more-info"] == "panel-view"
    assert parser.parent_by_id["chk-auto-view"] == "overview-settings-section"
    assert parser.parent_by_id["device-details"] == "panel-context-details"
    assert parser.parent_by_id["health-finding-details"] == "panel-context-details"
    assert parser.parent_by_id["topology-view"] == "topology-canvas-wrap"


def test_table_sorting_and_health_resets_are_application_owned_and_scoped() -> None:
    html = _read_text(HTML)
    table_js = (REPO_ROOT / "src" / "js" / "tdash-table-renderer.js").read_text(encoding="utf-8")
    health_js = (REPO_ROOT / "src" / "js" / "tdash-health.js").read_text(encoding="utf-8")
    ui_js = _read_text(UI_JS)

    assert "sortable.min.js" not in html
    assert 'class="sortable"' not in html
    assert "Sortable.init" not in table_js
    assert "button.className = \"table-sort-button\"" in table_js
    assert "tableIdentitySortKey" in table_js
    assert 'id="health-findings-sort"' in html
    assert 'id="btn-health-roster-reset"' in html
    assert '<label for="health-roster-search">Search name or canonical device ID' in html
    assert 'addEventListener("click", resetHealthFindings)' in ui_js
    assert 'addEventListener("click", resetHealthRoster)' in ui_js
    assert "updateSavedFindingNavigationContext();" in ui_js
    assert "updateSavedRosterNavigationContext();" in ui_js
    assert "attributed finding" in health_js


def test_health_insights_comparison_is_an_ordered_peer_tab() -> None:
    parser = _IdParentParser()
    html = _read_text(HTML)
    ui_text = _read_text(UI_JS)
    parser.feed(html)

    tabs = [
        ("health-tab-findings", "health-panel-findings"),
        ("health-tab-comparison", "health-panel-comparison"),
        ("health-tab-roster", "health-panel-roster"),
    ]
    assert [html.index(f'id="{button_id}"') for button_id, _ in tabs] == sorted(
        html.index(f'id="{button_id}"') for button_id, _ in tabs
    )
    for button_id, panel_id in tabs:
        assert parser.attributes_by_id[button_id]["role"] == "tab"
        assert parser.attributes_by_id[button_id]["aria-controls"] == panel_id
        assert parser.attributes_by_id[panel_id]["role"] == "tabpanel"
        assert parser.attributes_by_id[panel_id]["aria-labelledby"] == button_id
    assert parser.parent_by_id["health-comparison"] == "health-panel-comparison"
    assert parser.attributes_by_id["health-tab-findings"]["aria-selected"] == "true"
    assert parser.attributes_by_id["health-tab-findings"]["tabindex"] == "0"
    assert parser.attributes_by_id["health-tab-comparison"]["aria-selected"] == "false"
    assert parser.attributes_by_id["health-tab-roster"]["aria-selected"] == "false"
    assert 'id="health-mode-switch"' not in html
    assert 'id="health-mode-snapshot"' not in html
    assert 'id="health-mode-comparison"' not in html
    assert 'const HEALTH_INSIGHTS_TABS = [' in ui_text
    assert 'let healthInsightsTab = HEALTH_INSIGHTS_TABS[0].id;' in ui_text
    assert 'healthInsightsTab === "comparison" && currentView === "insights"' in ui_text
    assert "ensureHealthComparisonLoaded();" in ui_text


def test_health_insights_header_is_common_and_preserves_panel_ownership() -> None:
    parser = _IdParentParser()
    html = _read_text(HTML)
    css = _read_text(CSS)
    parser.feed(html)

    for element_id, parent_id in (
        ("health-insights-summary", "view-insights"),
        ("health-insights-navigation", "view-insights"),
        ("health-insights-tabs", "health-insights-navigation"),
    ):
        assert parser.inside_health_insights_sticky_by_id[element_id]
        assert not parser.inside_health_insights_workspace_by_id[element_id]
        assert parser.parent_by_id[element_id] == parent_id
    assert parser.inside_health_insights_workspace_by_id["health-panel-findings"]
    assert parser.inside_health_insights_workspace_by_id["health-panel-comparison"]
    assert parser.inside_health_insights_workspace_by_id["health-panel-roster"]
    assert "hidden" in parser.attributes_by_id["health-insights-navigation"]
    assert "hidden" in parser.attributes_by_id["health-insights-workspace"]
    assert parser.attributes_by_id["health-findings-count"]["aria-hidden"] == "true"
    assert parser.attributes_by_id["health-roster-count"]["aria-hidden"] == "true"
    assert re.search(
        r'<div class="health-insights-heading-row">\s*'
        r'<h2>Insights: Health\s*'
        r'(<svg class="control-icon health-pulse-icon"[^>]*>\s*'
        r'<path d="M2 13h4l3-8 5 14 3-8 2 2h3"/>\s*</svg>)\s*</h2>\s*'
        r'<div id="health-insights-summary" hidden></div>\s*</div>',
        html,
    )
    pulse = re.search(r'<svg class="control-icon health-pulse-icon"[^>]*>', html)
    assert pulse is not None
    for attribute in (
        'width="20" height="20"', 'stroke="currentColor" stroke-width="1.8"',
        'aria-hidden="true" focusable="false"',
    ):
        assert attribute in pulse[0]
    assert "#health-insights-summary[hidden] { display: none; }" in css
    assert "min-height: 44px;" in css[css.index("#health-insights-tabs button {"):]


def test_topology_controls_use_container_layout_and_native_legend_disclosure() -> None:
    parser = _IdParentParser()
    html = _read_text(HTML)
    css = _read_text(CSS)
    ui_text = _read_text(UI_JS)
    parser.feed(html)

    assert parser.tag_by_id["topology-title"] == "h2"
    assert parser.parent_by_id["topology-title"] == "view-topology"
    assert parser.parent_by_id["topology-toolbar-row"] == "topology-canvas-wrap"
    assert parser.parent_by_id["topology-controls"] == "topology-toolbar-row"
    assert parser.tag_by_id["lq-legend"] == "details"
    assert parser.parent_by_id["lq-legend"] == "topology-toolbar-row"
    assert "open" not in parser.attributes_by_id["lq-legend"]
    assert html.index('id="lq-legend"') < html.index('id="topology-controls"')
    assert html.index('id="topology-controls"') < html.index('id="topology-view"')
    assert "<summary>Legend</summary>" in html
    assert parser.parent_by_id["node-role-legend"] == "lq-legend"
    for role in ("border-router", "router", "reed", "med", "sed", "child", "unknown", "eve"):
        assert f"node-role-symbol node-role-{role}" in html
    assert "MTD alone does not mean sleepy" in html
    assert 'aria-label="Physics simulation"' in html
    assert "container: topology / inline-size;" in css
    assert "@container topology (max-width: 420px)" in css
    assert "grid-template-columns: max-content minmax(0, max-content) 34px;" in css
    assert "display: contents;" in css
    assert "padding: 4px 22px 4px 6px;" in css
    assert "background-size: 16px 16px;" in css
    assert "@media (min-width: 721px) and (max-height: 600px)" in css
    assert 'aria-pressed="true"' in html
    assert 'btn.setAttribute("aria-pressed", String(enabled));' in ui_text
    assert 'btn.title = "Pause physics simulation";' in ui_text
    assert 'btn.title = "Resume physics simulation";' in ui_text
    assert "flex: 0 0 34px;" in css
    for suffix in ("", "::before", ":hover", ":focus-visible"):
        assert (
            f"div.vis-network div.vis-navigation div.vis-button{suffix},\n"
            f"#btn-physics{suffix} {{"
        ) in css
    assert '#btn-physics[aria-pressed="true"] {' in css
    assert "min-height: 400px;" in css
    assert "min-height: 240px;" in css


def test_health_assessment_picker_fits_contents_with_mobile_width_cap() -> None:
    css = _read_text(CSS)
    picker = re.search(r"\.health-assessment-chooser-body select \{([^}]+)\}", css)
    assert picker is not None
    for declaration in (
        "justify-self: start;", "width: auto;", "max-width: 100%;",
        "min-width: 0;", "min-height: 44px;",
    ):
        assert declaration in picker.group(1)


def test_workspace_switch_registry_owns_all_five_views() -> None:
    ui_text = _read_text(UI_JS)
    html = _read_text(HTML)
    registry_start = ui_text.index("const WORKSPACE_VIEWS")
    switch_end = ui_text.index("// ── Physics toggle", registry_start)
    switch_source = ui_text[registry_start:switch_end]

    for view in ("topology", "table", "insights", "settings", "operations"):
        assert f'view: "{view}"' in switch_source
    assert html.index('id="btn-operations"') < html.index('id="btn-settings"')
    assert switch_source.index('view: "operations"') < switch_source.index('view: "settings"')
    assert "panelEl.hidden = !isActive;" in switch_source
    assert 'buttonEl.setAttribute("aria-selected", String(isActive));' in switch_source
    assert "buttonEl.tabIndex = isActive ? 0 : -1;" in switch_source
    assert "WORKSPACE_VIEWS.forEach(({ view, buttonId }, index)" in switch_source
    assert 'const navigationKeys = ["ArrowLeft", "ArrowRight", "Home", "End"];' in switch_source


def test_workspace_lifecycle_and_activity_contract() -> None:
    ui_text = _read_text(UI_JS)
    dataset_text = _read_text(DATASET_JS)

    assert "const lastRenderedDatasetByView = new Map();" in ui_text
    assert "renderedState?.dataset === currentDataset" in ui_text
    activation_index = ui_text.index("activateViewStatus(view, currentDataset);")
    cache_return_index = ui_text.index("renderedState?.dataset === currentDataset")
    assert activation_index < cache_return_index
    assert "supersedeViewStatus(`Loading ${selectedDataset?.label ?? selectedValue}…`);" in ui_text
    assert "rendersDataset: true" in ui_text
    assert "onActivate: resizeAndFitTopology" in ui_text
    assert "network.setSize" in ui_text
    assert "network.redraw();" in ui_text
    assert "handleDetailsPanelVisibilityChanged" in ui_text
    assert 'classList.toggle(\n    "details-panel-collapsed"' in ui_text
    assert "setFunctionsPanelCollapsed" in ui_text
    assert '"functions-panel-collapsed"' in ui_text
    activity_text = _read_text(REPO_ROOT / "src" / "js" / "tdash-activity.js")
    assert "const ACTIVITY_LIMIT = 200" in activity_text
    assert "activityEntries.splice" in activity_text
    assert "setDatasetActivityObserver" in ui_text
    assert 'userInitiated: true' in ui_text
    assert '["topology", "table"].includes(selectedDataset?.defaultView)' in ui_text
    assert "export function setDatasetActivityObserver" in dataset_text
    assert '"api-request"' not in dataset_text
    assert '"api-response"' not in dataset_text
    assert '"api-error"' not in dataset_text
    assert '"job-status"' in dataset_text
    assert "response.json()" in dataset_text
    assert "response.headers" not in ui_text[ui_text.index("function renderWorkspaceLogs"):ui_text.index("export function getSearchQuery")]


def test_workspace_cached_views_reapply_current_filters() -> None:
    script = r"""
      import assert from "node:assert/strict";
      import fs from "node:fs";
      import vm from "node:vm";

      const ui = fs.readFileSync("src/js/tdash-ui.js", "utf8");
      const start = ui.indexOf("function renderCurrentView(");
      const end = ui.indexOf("\nfunction clearRenderedDatasetViews", start);
      assert.ok(start >= 0 && end > start);
      const topologyCapabilities = {view: "topology"};
      const tableCapabilities = {view: "table"};
      const renders = [];
      const calls = [];
      const context = {
        currentDataset: {rows: [{isReed: true}, {isReed: false}]},
        currentView: "topology",
        threadNetworkModelCache: null,
        lastRenderedDatasetByView: new Map(),
        _enhanceEnabled: false,
        _physicsEnabled: false,
        _currentSearchQuery: "",
        _physicsProfileName: "auto",
        nodeFilter: "all",
        diagnosticFilter: "all",
        visibleCount: 0,
        updateHealthPresentationControls() {},
        renderNetworkInsights() {},
        activateViewStatus() {},
        setPhysics() {},
        getEffectivePhysicsProfileName() { return "auto"; },
        getSelectedDatasetEntry() { return {}; },
        getTopologyDatasetCounts() { return {nodes: 2}; },
        updateDeviceStatusBar() {},
        computeRowCounts() { return {nodes: 2}; },
        runAdaptor() { return {}; },
        projectObservedTopologyLinkCounts(rows) { return {rows}; },
        populateTableColumnCategories() {},
        updateFilterOptionVisibility(capabilities, view) {
          assert.equal(capabilities.view, view);
          calls.push(`capabilities:${view}`);
        },
        refreshDiagnosticFilterForCurrentSource() {
          assert.equal(context.currentDataset.capabilities.view, context.currentView);
          calls.push(`diagnostics:${context.currentView}`);
        },
        refreshTopologyFiltersWithRestoredStyling() {
          context.visibleCount = context.nodeFilter === "reed-devices" ? 1 : 2;
          calls.push(`topology:${context.nodeFilter}:${context.diagnosticFilter}`);
        },
        applyTableFilters() {
          context.visibleCount = context.nodeFilter === "reed-devices" ? 1 : 2;
          calls.push(`table:${context.nodeFilter}:${context.diagnosticFilter}`);
        },
        applySearch() { calls.push("search"); },
        renderTopologyForDataset(dataset) {
          dataset.capabilities = topologyCapabilities;
          renders.push("topology");
        },
        renderTableForDataset(dataset) {
          dataset.capabilities = tableCapabilities;
          renders.push("table");
        },
      };
      vm.createContext(context);
      vm.runInContext(ui.slice(start, end), context);
      context.renderCurrentView();
      context.currentView = "table";
      context.renderCurrentView();
      assert.deepEqual(renders, ["topology", "table"]);
      assert.equal(context.currentDataset.capabilities, tableCapabilities);
      assert.equal(
        context.lastRenderedDatasetByView.get("topology").capabilities,
        topologyCapabilities,
      );

      calls.length = 0;
      context.currentView = "topology";
      context.nodeFilter = "reed-devices";
      context.diagnosticFilter = "example-diagnostic";
      context._currentSearchQuery = "example";
      context.renderCurrentView();
      assert.equal(context.visibleCount, 1);
      assert.deepEqual(calls, [
        "capabilities:topology", "diagnostics:topology",
        "topology:reed-devices:example-diagnostic", "search",
      ]);
      assert.equal(context.currentDataset.capabilities, topologyCapabilities);

      calls.length = 0;
      context.currentView = "table";
      context.renderCurrentView();
      assert.equal(context.visibleCount, 1);
      assert.deepEqual(calls, [
        "capabilities:table", "diagnostics:table",
        "table:reed-devices:example-diagnostic",
      ]);
      context.nodeFilter = "all";
      context.diagnosticFilter = "all";
      context._currentSearchQuery = "";
      for (const view of ["topology", "table"]) {
        context.currentView = view;
        context.renderCurrentView();
        assert.equal(context.visibleCount, 2);
      }
      assert.deepEqual(renders, ["topology", "table"]);
      context.renderCurrentView({force: true});
      assert.deepEqual(renders, ["topology", "table", "table"]);
      context.currentDataset = {rows: []};
      context.renderCurrentView();
      assert.deepEqual(renders, ["topology", "table", "table", "table"]);
      assert.equal(context.currentDataset.capabilities, tableCapabilities);
      context.renderCurrentView();
      assert.equal(context.currentDataset.capabilities, tableCapabilities);
    """
    subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_operations_workspace_exposes_activity_and_jobs_tabs() -> None:
    html = _read_text(HTML)
    ui_text = _read_text(UI_JS)

    for element_id in (
        "btn-thread-network",
        "btn-activity-log",
        "btn-jobs",
        "workspace-thread-network-panel",
        "workspace-log-panel",
        "workspace-jobs-panel",
        "btn-clear-logs",
        "btn-refresh-jobs",
        "btn-cancel-all-jobs",
        "workspace-jobs-content",
    ):
        assert f'id="{element_id}"' in html
    assert 'role="tablist" aria-label="Operations"' in html
    assert '["thread-network", "btn-thread-network", "workspace-thread-network-panel"]' in ui_text
    assert '["logs", "btn-activity-log", "workspace-log-panel"]' in ui_text
    assert '["jobs", "btn-jobs", "workspace-jobs-panel"]' in ui_text
    assert 'aria-controls="workspace-log-panel"' in html
    assert 'aria-controls="workspace-jobs-panel"' in html
    assert 'trackedFetch("/api/jobs"' in ui_text
    assert '}, "silent");' in ui_text
    assert "new AbortController()" in ui_text
    assert "jobsViewState.requestVersion" in ui_text
    assert 'window.confirm("Cancel all pending jobs?")' in ui_text


def test_device_status_close_button_toggles_functions_panel() -> None:
    parser = _IdParentParser()
    html = _read_text(HTML)
    css = _read_text(CSS)
    ui_text = _read_text(UI_JS)
    parser.feed(html)

    assert parser.parent_by_id["btn-device-status-close"] == "device-status"
    assert parser.parent_by_id["btn-toggle-devices"] == "device-status"
    assert parser.tag_by_id["btn-device-status-close"] == "button"
    close_button = parser.attributes_by_id["btn-device-status-close"]
    assert close_button["type"] == "button"
    assert close_button["title"] == "Collapse functions panel"
    assert close_button["aria-label"] == "Collapse functions panel"
    assert close_button["aria-controls"] == "panel-functions"
    assert close_button["aria-expanded"] == "true"
    assert 'class="device-status-close"' in html
    assert "#device-status > legend" in css
    assert "justify-content: space-between;" in css
    header = re.search(r"#device-status > legend\s*\{([^}]+)\}", css)
    assert header is not None
    assert "padding: 10px;" in header[1]
    assert re.search(r"\.device-status-close\s*\{", css) is None
    assert (
        'document.getElementById("btn-functions-panel-toggle")?.addEventListener("click", toggleFunctionsPanel);'
        in ui_text
    )
    assert (
        'document.getElementById("btn-device-status-close")?.addEventListener("click", toggleFunctionsPanel);'
        in ui_text
    )
    assert 'button.setAttribute("aria-expanded", String(!isCollapsed));' in ui_text


def test_jobs_workspace_poll_delay_scales_with_longest_running_job() -> None:
    ui_text = _read_text(UI_JS)
    poll_start = ui_text.index("function getJobsPollDelayMs")
    poll_end = ui_text.index("async function refreshWorkspaceJobs", poll_start)
    poll_source = ui_text[poll_start:poll_end]

    assert "JOBS_POLL_MIN_DELAY_MS = 2000" in ui_text
    assert "JOBS_POLL_EMPTY_DELAY_MS = 10000" in ui_text
    assert "JOBS_POLL_MAX_DELAY_MS = 60_000" in ui_text
    assert "if (jobs.length === 0) return JOBS_POLL_EMPTY_DELAY_MS;" in poll_source
    assert "Math.max(0, Number(job.elapsedSeconds) || 0)" in poll_source
    assert "maxElapsedSeconds * 500" in poll_source
    assert "JOBS_POLL_MAX_DELAY_MS" in poll_source


def test_details_collapse_targets_explicit_details_owner_and_notifies_renderer() -> None:
    utils_text = _read_text(UTILS_JS)
    controller_start = utils_text.index("export function initContextDetailsPanel")
    controller_end = utils_text.index("export function mergeForDisplay", controller_start)
    controller_source = utils_text[controller_start:controller_end]

    assert 'host?.classList.toggle("details-panel-collapsed"' in controller_source
    assert 'host?.querySelector("#device-details")' in controller_source
    assert 'host?.querySelector("#health-finding-details")' in controller_source
    assert "onVisibilityChanged?.(isCollapsed);" in controller_source
    assert 'toggleButton.textContent = isCollapsed ? "◀" : "▶";' in controller_source
    assert "setCollapsed," in controller_source
    assert "setMode," in controller_source


def test_device_details_heading_close_uses_shared_cleanup_and_restores_focus() -> None:
    utils_text = _read_text(UTILS_JS)
    toggles_start = utils_text.index("export function initDetailPanelToggles")
    toggles_end = utils_text.index("export function initContextDetailsPanel", toggles_start)
    toggles_source = utils_text[toggles_start:toggles_end]
    close_button_start = toggles_source.index('closeBtn.id = "btn-device-details-heading-close"')
    close_button_source = toggles_source[close_button_start:]

    assert 'closeBtn.type = "button";' in close_button_source
    assert 'closeBtn.title = "Close device details panel";' in close_button_source
    assert 'closeBtn.setAttribute("aria-label", "Close device details panel");' in close_button_source
    assert 'closeBtn.textContent = "✕";' in close_button_source
    assert 'closeBtn.setAttribute("aria-expanded"' not in close_button_source
    assert toggles_source.index("headerActions.appendChild(allBtn);") < toggles_source.index(
        "headerActions.appendChild(closeBtn);"
    )
    assert "closeBtn.addEventListener(\"click\", onClose);" in close_button_source

    ui_text = _read_text(UI_JS)
    assert "closeDeviceDetailsPanel({ restoreFocus: true })" in ui_text
    assert "btn-device-details-close" not in _read_text(HTML)
    assert "btn-device-details-close" not in ui_text
    assert 'id="btn-back-to-health-finding"' in _read_text(HTML)
    close_action_start = ui_text.index("function closeDeviceDetailsPanel")
    close_action_end = ui_text.index("\n}\n", close_action_start)
    close_action_source = ui_text[close_action_start:close_action_end]

    invalidation = close_action_source.index("rosterNavigationGeneration += 1;")
    selected_device_clear = close_action_source.index("healthRosterViewState.selectedDeviceId = null;")
    roster_detail_clear = close_action_source.index("healthInsightsState.rosterDetail = null;")
    selection_class_clear = close_action_source.index('classList.remove("roster-selected")')
    collapse = close_action_source.index("contextDetailsController.setCollapsed(true);")
    restore_focus = close_action_source.index("requestAnimationFrame(")
    assert invalidation < selected_device_clear < roster_detail_clear < selection_class_clear < collapse
    assert collapse < restore_focus
    assert 'document.getElementById("btn-details-panel-toggle")?.focus()' in close_action_source


def test_insights_activation_collapses_context_details_panel() -> None:
    ui_text = _read_text(UI_JS)
    insights_start = ui_text.index('view: "insights"')
    insights_end = ui_text.index('view: "settings"', insights_start)
    insights_source = ui_text[insights_start:insights_end]

    assert "contextDetailsController.setCollapsed(true);" in insights_source
    assert "renderNetworkInsights();" in insights_source
    assert "contextDetailsController = initContextDetailsPanel({" in ui_text


def test_dataset_health_refresh_preserves_context_details_visibility() -> None:
    ui_text = _read_text(UI_JS)
    dataset_reset_start = ui_text.index("function resetHealthInsightsForDatasetChange()")
    network_reset_start = ui_text.index("function resetHealthInsightsForNetworkChange()")
    refresh_start = ui_text.index("async function refreshHealthAssessment()")
    dataset_change_source = ui_text[dataset_reset_start:network_reset_start]
    network_change_source = ui_text[network_reset_start:refresh_start]
    refresh_source = ui_text[refresh_start:ui_text.index("\nfunction ", refresh_start)]

    assert 'setContextDetailsMode("device");' in dataset_change_source
    assert "contextDetailsController.setCollapsed" not in dataset_change_source
    assert "contextDetailsController.setCollapsed(true);" in network_change_source
    assert "if (datasetChanged) resetHealthInsightsForDatasetChange();" in refresh_source
    assessment_read = refresh_source.index("const assessment = await fetchHealthAssessment(")
    version_guard = refresh_source.index(
        "if (!isCurrent()) return;",
        assessment_read,
    )
    assert assessment_read < version_guard < refresh_source.index(
        "if (networkChanged) resetHealthInsightsForNetworkChange();",
    )


def test_vis_navigation_rules_are_not_nested_under_unused_heading() -> None:
    css = _read_text(CSS)

    assert re.search(r"h1\s*\{[^}]*div\.vis-network", css, re.DOTALL) is None


def test_roster_header_stacks_above_sticky_device_cells() -> None:
    css = _read_text(CSS)
    header = re.search(r"\.health-roster-table-wrap thead\s*\{([^}]+)\}", css)
    device_cells = re.search(
        r"\.health-roster-table-wrap th:first-child,\s*"
        r"\.health-roster-table-wrap td:first-child\s*\{([^}]+)\}", css,
    )
    assert header is not None
    assert device_cells is not None
    header_rules = header.group(1)
    device_rules = device_cells.group(1)
    assert "position: sticky;" in header_rules
    assert "top: 0;" in header_rules
    assert "position: sticky;" in device_rules
    assert "left: 0;" in device_rules
    header_z = re.search(r"z-index:\s*(\d+)", header_rules)
    device_z = re.search(r"z-index:\s*(\d+)", device_rules)
    assert header_z is not None
    assert device_z is not None
    assert int(header_z.group(1)) > int(device_z.group(1))


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
    assert "grid-template-columns: 44px minmax(0, 1fr);" in css
    assert "grid-template-columns: repeat(5, 44px);" in css


def test_navigation_panel_supports_expanded_and_icon_only_states() -> None:
    html = _read_text(HTML)
    css = _read_text(CSS)
    ui_text = _read_text(UI_JS)

    assert 'id="btn-navigation-panel-toggle"' in html
    assert 'class="page dashboard-shell navigation-panel-collapsed"' in html
    assert 'title="Show icons and labels"' in html
    assert 'aria-expanded="false">▶</button>' in html
    assert html.count('class="workspace-navigation-tab-icon"') == 5
    assert html.count('class="workspace-navigation-tab-label"') == 5
    assert "setNavigationPanelCollapsed" in ui_text
    assert '"navigation-panel-collapsed"' in ui_text
    assert "--navigation-panel-width: 132px;" in css
    assert "--navigation-panel-width: 50px;" in css
    assert ".workspace-navigation-tab-label" in css
    assert "grid-template-columns: 44px minmax(0, 1fr);" in css
    assert "grid-template-columns: repeat(5, 44px);" in css
    assert "overflow-x: auto;" in css
    assert "scrollbar-width: none;" in css
    assert "width: 240px;" not in css


def test_desktop_navigation_is_compact_without_shrinking_mobile_targets() -> None:
    css = _read_text(CSS)
    desktop_start = css.index("@media (min-width: 721px) {\n  .dashboard-shell")
    desktop_end = css.index("@media (min-width: 721px) and (max-height: 600px)", desktop_start)
    desktop = css[desktop_start:desktop_end]
    for selector in (
        "#panel-navigation .workspace-navigation-controls button",
        "#panel-navigation .workspace-navigation-tabs button",
    ):
        rules = re.search(re.escape(selector) + r"\s*\{([^}]+)\}", desktop)
        assert rules is not None
        assert "height: 32px;" in rules[1]
        assert "min-height: 32px;" in rules[1]
    assert "min-width: 32px;" in desktop
    assert "grid-template-columns: repeat(5, 32px);" in desktop
    assert "width: auto;" in desktop
    assert "align-items: flex-start;" in desktop
    assert "--navigation-panel-width: 50px;" in desktop
    mobile = css[css.index("@media (max-width: 720px)"):]
    assert "min-height: 44px;" in mobile
    assert "grid-template-columns: repeat(5, 44px);" in mobile


def test_detail_disclosures_use_heading_text_hierarchy() -> None:
    css = _read_text(CSS)
    toggle = re.search(r"\.node-details-panel \.detail-section-toggle \{([^}]+)\}", css)
    assert toggle is not None
    assert "font-weight: 650;" in toggle[1]
    assert "color: var(--text);" in toggle[1]
    assert "padding: 0;" in toggle[1]


def test_compact_controls_are_scoped_to_desktop_actions() -> None:
    css = _read_text(CSS)
    desktop = css[
        css.index("@media (min-width: 721px) {\n  .dashboard-shell"):
        css.index("@media (min-width: 1124px)")
    ]
    controls = re.search(r"#panel-functions select,\s*#panel-functions #search-input \{([^}]+)\}", desktop)
    assert controls is not None
    for declaration in ("box-sizing: border-box;", "height: 30px;", "padding-block: 4px;"):
        assert declaration in controls[1]
    labels = re.search(r"#panel-functions #panel-dataset \.control-pair \{([^}]+)\}", desktop)
    assert labels is not None
    assert "grid-template-columns: 56px minmax(0, 1fr);" in labels[1]
    actions = re.search(r"#btn-fetch,\s*(.*?)#device-details-nav-bar-left button \{([^}]+)\}", desktop, re.S)
    assert actions is not None
    for declaration in ("height: 32px;", "min-height: 32px;", "padding: 4px 8px;"):
        assert declaration in actions[2]
    for excluded in ("legend-toggle-btn", "detail-section-toggle", "btn-physics", "theme-toggle"):
        assert excluded not in actions[1]
    icons = re.search(r"#btn-functions-panel-toggle,\s*#btn-details-panel-toggle,\s*#device-details-nav-bar-left button \{([^}]+)\}", desktop)
    assert icons is not None
    assert "width: 32px;" in icons[1]
    assert "padding: 4px;" in icons[1]
