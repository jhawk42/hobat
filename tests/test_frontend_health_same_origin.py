"""Browser health requests stay on the dashboard's direct or proxied origin."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_health_comparison_dropdown_uses_relative_times_without_changing_selection() -> None:
    script = r"""
      import {renderHealthComparison} from "./src/js/tdash-health.js";

      const now = Date.parse("2026-09-24T12:00:00Z");
      Date.now = () => now;
      class Element {
        constructor(tagName) {
          this.tagName = tagName;
          this.children = [];
          this.listeners = {};
          this.parentNode = null;
        }
        appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
        replaceChildren() {
          this.children.forEach((child) => { child.parentNode = null; });
          this.children = [];
        }
        remove() {
          if (!this.parentNode) return;
          this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
          this.parentNode = null;
        }
        setAttribute(name, value) { this[name] = value; }
        addEventListener(name, listener) { this.listeners[name] = listener; }
      }
      globalThis.document = {createElement: (tagName) => new Element(tagName)};

      const page = {total: 6, offset: 0, limit: 3, items: [
        {comparisonId: "pair-1", beforeObservedAt: "2026-09-23T07:48:00Z",
          afterObservedAt: "2026-09-24T11:54:00Z"},
        {comparisonId: "pair-2", beforeObservedAt: "2026-09-24T11:59:01Z",
          afterObservedAt: "2026-09-24T12:01:00Z"},
        {comparisonId: "pair-3", beforeObservedAt: null, afterObservedAt: "invalid"},
      ]};
      const comparison = {comparisonId: "pinned", beforeObservedAt: "2026-09-24T11:00:00Z",
        afterObservedAt: "2026-09-24T11:59:00Z", itemCount: 0, filteredItemCount: 0,
        offset: 0, limit: 25, items: [], reasons: []};
      const selected = [];
      const paged = [];
      const resultFilters = [];
      const container = new Element("section");
      renderHealthComparison(container, page, comparison, {}, {
        select: (id) => selected.push(id), page: (offset) => paged.push(offset),
        result: (value) => resultFilters.push(value),
      });
      const controls = container.children.find((item) => item.className === "health-comparison-controls");
      const picker = controls.children[0];
      const filterRow = container.children.find((item) => item.className === "health-comparison-filter-row");
      const resultFilter = filterRow.children[1];
      const navigation = container.children.find((item) => item.className === "health-comparison-navigation");
      const heading = container.children.find((item) => item.className === "health-comparison-pair-summary");
      const selectedValue = picker.value;
      picker.value = "pair-1";
      picker.listeners.change();
      resultFilter.value = "unknown";
      resultFilter.listeners.change();
      navigation.children[1].listeners.click();
      console.log(JSON.stringify({
        options: picker.children.map(({value, textContent}) => [value, textContent]),
        resultOptions: resultFilter.children.map(({value, textContent}) => [value, textContent]),
        selectedValue, selected, resultFilters, paged, heading: heading.textContent,
      headingTitle: heading.title,
      count: filterRow.children.find((item) => item.className === "health-comparison-row-count").textContent,
      total: filterRow.children.find((item) => item.className === "health-comparison-total-count").textContent,
      }));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script], cwd=ROOT,
        check=True, capture_output=True, text=True,
    )
    result = json.loads(completed.stdout)

    assert result == {
        "options": [
            ["", "Select a comparison"],
            ["pair-1", "Before: 1d 4h 12m · After: 6m"],
            ["pair-2", "Before: 0m · After: 0m"],
            ["pair-3", "Before: unknown · After: unknown"],
            ["pinned", "Before: 1h 0m · After: 1m (selected)"],
        ],
        "resultOptions": [
            ["changed", "Changed"],
            ["unchanged", "Unchanged"],
            ["unknown", "Unknown"],
            ["all", "All results"],
        ],
        "selectedValue": "pinned",
        "selected": ["pair-1"],
        "resultFilters": ["unknown"],
        "paged": [3],
        "heading": "Before 2026-09-24 11:00:00 → After 2026-09-24 11:59:00 UTC · unknown",
        "headingTitle": "Before 2026-09-24T11:00:00Z · After 2026-09-24T11:59:00Z",
        "count": "0 matching rows",
        "total": "0 total rows",
    }


def test_health_comparison_availability_and_empty_history_states_are_distinct() -> None:
    script = r"""
      import {renderHealthComparison} from "./src/js/tdash-health.js";

      class Element {
        constructor(tagName) {
          this.tagName = tagName;
          this.children = [];
          this.listeners = {};
        }
        appendChild(child) { this.children.push(child); return child; }
        replaceChildren() { this.children = []; }
        setAttribute(name, value) { this[name] = value; }
        addEventListener(name, listener) { this.listeners[name] = listener; }
      }
      globalThis.document = {
        activeElement: null,
        createElement: (tagName) => new Element(tagName),
      };
      const render = (state, actions = {}, page = null, comparison = null) => {
        const container = new Element("section");
        renderHealthComparison(container, page, comparison, state, actions);
        return container;
      };
      const textContent = (element) => [
        element.textContent || "",
        ...element.children.map(textContent),
      ].join(" ");
      const loading = render({supportLoading: true});
      const unsupported = render({capabilityKnown: true, comparisonReadModel: false});
      let retried = 0;
      const failed = render({capabilityKnown: false, supportError: "offline"}, {
        retry: () => { retried += 1; },
      });
      failed.children.find((child) => child.tagName === "button").listeners.click();
      let detailRetried = 0;
      const legacyDetailFailure = render({
        capabilityKnown: true,
        comparisonReadModel: true,
        endpointSelection: false,
        comparisonId: "pair",
        detailError: "offline",
      }, {
        retry: () => { retried += 1; },
        retryDetail: () => { detailRetried += 1; },
      }, {total: 1, offset: 0, limit: 25, items: [
        {comparisonId: "pair", beforeObservedAt: null, afterObservedAt: null},
      ]});
      legacyDetailFailure.children.find(
        (child) => child.tagName === "button" && child.textContent === "Retry comparison read",
      ).listeners.click();
      const higherPriorityFailure = render({
        capabilityKnown: true,
        comparisonReadModel: true,
        supportError: "offline",
        comparisonId: "pair",
        detailError: "stale detail error",
      }, {
        retry: () => { retried += 1; },
        retryDetail: () => { detailRetried += 1; },
      });
      higherPriorityFailure.children.find(
        (child) => child.tagName === "button" && child.textContent === "Retry comparison read",
      ).listeners.click();
      const insufficient = render({
        capabilityKnown: true,
        comparisonReadModel: true,
        endpointSelection: true,
        endpointPages: {
          before: null,
          after: {total: 0, offset: 0, limit: 25, items: [], shortcuts: []},
        },
        endpointLoading: {before: false, after: false},
        endpointErrors: {before: "", after: ""},
      });
      const emptyLegacy = new Element("section");
      renderHealthComparison(emptyLegacy, {total: 0, offset: 0, limit: 25, items: []}, null, {
        capabilityKnown: true,
        comparisonReadModel: true,
        endpointSelection: false,
      });
      console.log(JSON.stringify({
        loading: textContent(loading),
        unsupported: textContent(unsupported),
        failed: textContent(failed),
        failedRole: failed.children[0].role,
        retryLabel: failed.children[1].textContent,
        retried, detailRetried,
        unavailableHistory: textContent(insufficient),
        emptyLegacy: textContent(emptyLegacy),
      }));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script], cwd=ROOT,
        check=True, capture_output=True, text=True,
    )
    result = json.loads(completed.stdout)

    assert "Loading comparison availability" in result["loading"]
    assert "does not support comparison reads" in result["unsupported"]
    assert "availability could not be loaded: offline" in result["failed"]
    assert result["failedRole"] == "alert"
    assert result["retryLabel"] == "Retry comparison read"
    assert result["retried"] == 2
    assert result["detailRetried"] == 1
    assert "Not enough history" in result["unavailableHistory"]
    assert "Not enough retained history" in result["emptyLegacy"]


def test_legacy_comparison_detail_retry_reloads_selected_pair() -> None:
    script = r"""
      import {createHealthComparisonDetailController} from "./src/js/tdash-health.js";

      const state = {
        comparisonDetailRequestVersion: 0,
        comparisonDetailError: "",
        comparisonDetailLoading: false,
        comparisonDetailRequestIdentity: null,
        comparisonDetailRequestHeader: null,
        comparison: null,
        comparisonQueryIdentity: null,
      };
      const assessment = {networkId: "network", datasetId: "dataset"};
      const selection = {comparisonId: "pair", scope: "all", result: "changed"};
      let offset = 0;
      let attempts = 0;
      const controller = createHealthComparisonDetailController({
        state,
        getAssessment: () => assessment,
        getSelection: () => selection,
        getSummary: () => null,
        getOffset: () => offset,
        setOffset: (value) => { offset = value; },
        updateSelection: () => {},
        fetchDetail: async (comparisonId, requestedOffset) => {
          attempts += 1;
          if (attempts === 1) throw new Error("offline");
          return {
            schemaVersion: 1, comparisonId, networkId: "network", datasetId: "dataset",
            itemCount: 1, filteredItemCount: 1, limit: 25, offset: requestedOffset,
            items: [{itemId: "item", scope: "device", subjectId: "device"}],
          };
        },
      });
      await controller.select("pair", offset);
      const firstError = state.comparisonDetailError;
      await controller.retrySelected();
      console.log(JSON.stringify({
        firstError, attempts, finalError: state.comparisonDetailError,
        comparisonId: state.comparison?.comparisonId ?? null,
        offset,
      }));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script], cwd=ROOT,
        check=True, capture_output=True, text=True,
    )
    result = json.loads(completed.stdout)

    assert result == {
        "firstError": "offline",
        "attempts": 2,
        "finalError": "",
        "comparisonId": "pair",
        "offset": 0,
    }


def test_comparison_detail_query_and_page_validation() -> None:
    script = r"""
      import {
        fetchHealthComparison,
        isHealthComparisonDetailForQuery,
      } from "./src/js/tdash-health.js";

      const requested = [];
      globalThis.fetch = async (path) => {
        requested.push(path);
        return {ok: true, json: async () => ({})};
      };
      await fetchHealthComparison("comparison:a/b", 25, undefined, {
        scope: "relationship", result: "unknown",
      });
      await fetchHealthComparison("comparison:old-signature", 0);
      const query = {
        comparisonId: "comparison:one", networkId: "extpan:one",
        datasetId: "dataset-one", offset: 0,
      };
      const row = {itemId: "item:one"};
      const page = {
        schemaVersion: 1, comparisonId: query.comparisonId, networkId: query.networkId,
        datasetId: query.datasetId, offset: 0, limit: 25, itemCount: 30,
        filteredItemCount: 12, items: [row],
      };
      console.log(JSON.stringify({
        requested,
        valid: isHealthComparisonDetailForQuery(page, query),
        tooManyMatches: isHealthComparisonDetailForQuery({...page, filteredItemCount: 31}, query),
        invalidZeroPage: isHealthComparisonDetailForQuery({...page, items: []}, query),
        recoveredEmpty: isHealthComparisonDetailForQuery({...page, offset: 25, items: []},
          {...query, offset: 25}),
        noMatches: isHealthComparisonDetailForQuery({...page, filteredItemCount: 0, items: []}, query),
      }));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script], cwd=ROOT,
        check=True, capture_output=True, text=True,
    )
    result = json.loads(completed.stdout)
    assert result == {
        "requested": [
            "api/health/comparisons/comparison%3Aa%2Fb?limit=25&offset=25&scope=relationship&result=unknown",
            "api/health/comparisons/comparison%3Aold-signature?limit=25&offset=0&scope=all&result=changed",
        ],
        "valid": True,
        "tooManyMatches": False,
        "invalidZeroPage": False,
        "recoveredEmpty": True,
        "noMatches": True,
    }


def test_endpoint_selectors_use_pinned_ids_and_pair_read_contract() -> None:
    script = r"""
      import {
        fetchHealthComparisonEndpoints,
        fetchHealthComparisonPair,
        isHealthComparisonEndpointPageForQuery,
        isHealthComparisonPairForQuery,
        renderHealthComparison,
      } from "./src/js/tdash-health.js";

      Date.now = () => Date.parse("2026-09-24T12:00:00Z");
      class Element {
        constructor(tagName) {
          this.tagName = tagName;
          this.children = [];
          this.listeners = {};
          this.parentNode = null;
        }
        appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
        replaceChildren() {
          this.children.forEach((child) => { child.parentNode = null; });
          this.children = [];
        }
        remove() {
          if (!this.parentNode) return;
          this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
          this.parentNode = null;
        }
        setAttribute(name, value) { this[name] = value; }
        addEventListener(name, listener) { this.listeners[name] = listener; }
      }
      globalThis.document = {createElement: (tagName) => new Element(tagName)};
      const requested = [];
      globalThis.fetch = async (path) => {
        requested.push(path);
        return {ok: true, json: async () => ({})};
      };
      await fetchHealthComparisonEndpoints("extpan:net", "dataset", "before", 25,
        undefined, {afterAssessmentId: "assessment-after", selectedAssessmentId: "assessment-before"});
      await fetchHealthComparisonPair({
        networkId: "extpan:net", datasetId: "dataset",
        beforeAssessmentId: "assessment-before", afterAssessmentId: "assessment-after",
        comparisonPolicyDigest: "policy-digest", comparisonVersion: "comparison-v1",
        scope: "all", result: "changed",
      }, 0);

      const endpoint = (assessmentId, observedAt, completeness = "complete") => ({
        assessmentId, networkId: "extpan:net", datasetId: "dataset",
        observedAt, assessedAt: observedAt, completeness,
      });
      const before = endpoint("assessment-before", "2026-09-01T00:00:00.123Z", "partial");
      const after = endpoint("assessment-after", "2026-09-02T02:00:00.123+02:00");
      const beforePageItem = endpoint("assessment-page", "2026-08-30T00:00:00Z");
      const query = {
        networkId: "extpan:net", datasetId: "dataset", side: "before",
        afterAssessmentId: after.assessmentId, selectedAssessmentId: before.assessmentId,
        comparisonVersion: "comparison-v1", comparisonPolicyDigest: "policy-digest", offset: 0,
      };
      const endpointPage = {
        schemaVersion: 1, networkId: query.networkId, datasetId: query.datasetId,
        side: query.side, afterAssessmentId: query.afterAssessmentId,
        comparisonVersion: query.comparisonVersion,
        comparisonPolicyDigest: query.comparisonPolicyDigest,
        total: 2, limit: 25, offset: 0, items: [beforePageItem], selected: before,
        defaultAfter: after, defaultBefore: before, predecessor: before,
        shortcuts: [
          {interval: "1d", durationSeconds: 86400, candidate: before},
          {interval: "3d", durationSeconds: 259200, candidate: null},
          {interval: "1w", durationSeconds: 604800, candidate: null},
          {interval: "1m", durationSeconds: 2592000, candidate: beforePageItem},
        ],
      };
      const comparison = {
        schemaVersion: 1, networkId: query.networkId, datasetId: query.datasetId,
        beforeAssessmentId: before.assessmentId, afterAssessmentId: after.assessmentId,
        beforeObservedAt: before.observedAt, afterObservedAt: after.observedAt,
        elapsedSeconds: 86400,
        comparisonPolicyDigest: query.comparisonPolicyDigest,
        comparisonVersion: query.comparisonVersion, origin: "derived", createdAt: null,
        itemCount: 0, filteredItemCount: 0, limit: 25, offset: 0, items: [],
      };
      const selections = [];
      const shortcuts = [];
      const pages = [];
      const container = new Element("section");
      const viewState = {
        endpointSelection: true,
        latestPresetPage: endpointPage,
        endpointPages: {
          before: {...endpointPage, side: "before"},
          after: {...endpointPage, side: "after", afterAssessmentId: null, items: [after],
            selected: after, total: 1},
        },
        endpointLoading: {before: false, after: false},
        endpointErrors: {before: "", after: ""},
        before, after, beforeAssessmentId: before.assessmentId,
        afterAssessmentId: after.assessmentId, result: "changed", scope: "all",
        endpointPairLoading: false,
        customOpen: true, intent: "1d",
      };
      const actions = {
        endpointSelect: (side, id) => selections.push([side, id]),
        endpointPage: (side, offset) => pages.push([side, offset]),
        preset: (interval) => shortcuts.push([interval]),
      };
      renderHealthComparison(container, null, comparison, viewState, actions);
      const controls = container.children.find((item) => item.className === "health-comparison-controls");
      const customControls = container.children.find((item) => item.className === "health-comparison-custom");
      const liveStatus = container.children.find(
        (item) => item.className === "visually-hidden health-comparison-shortcut-status",
      );
      const beforeGroup = customControls.children[0];
      const afterGroup = customControls.children[1];
      const beforeSelect = beforeGroup.children[0].children[0];
      const afterSelect = afterGroup.children[0].children[0];
      const buttons = controls.children[0].children.filter((item) => item.tagName === "button");
      const heading = container.children.find((item) => item.className === "health-comparison-pair-summary");
      beforeSelect.value = after.assessmentId;
      beforeSelect.listeners.change();
      beforeGroup.children[1].children[1].listeners.click();
      buttons[0].listeners.click();
      buttons[1].listeners.click();
      const firstLiveStatus = liveStatus;
      viewState.endpointLoading.after = true;
      renderHealthComparison(container, null, comparison, viewState, actions);
      const loadingStatus = container.children.find(
        (item) => item.className === "visually-hidden health-comparison-shortcut-status",
      );
      const loadingButtons = container.children.find(
        (item) => item.className === "health-comparison-controls",
      ).children[0].children.filter((item) => item.tagName === "button");
      loadingButtons[0].listeners.click();
      console.log(JSON.stringify({
        endpointValid: isHealthComparisonEndpointPageForQuery(endpointPage, query),
        endpointRejectsWrongAfter: isHealthComparisonEndpointPageForQuery(endpointPage,
          {...query, afterAssessmentId: "assessment-other"}),
        pairValid: isHealthComparisonPairForQuery(comparison, {...query,
          beforeAssessmentId: before.assessmentId, afterAssessmentId: after.assessmentId,
          scope: "all", result: "changed", offset: 0}),
        presetLabels: buttons.map((item) => item.textContent),
        selectedPreset: buttons[0]["aria-pressed"],
        customDisclosure: [controls.children[0].children[4]["aria-expanded"],
          controls.children[0].children[4]["aria-controls"], customControls.hidden],
        beforeOptions: beforeSelect.children.map((item) => [
          item.value, item.textContent, item.title,
        ]),
        afterOptions: afterSelect.children.map((item) => [
          item.value, item.textContent, item.title,
        ]),
        heading: heading.textContent,
        headingTitle: heading.title,
        liveRegionConfigured: [liveStatus.role, liveStatus["aria-live"], liveStatus["aria-atomic"]],
        liveRegionPreserved: firstLiveStatus === loadingStatus,
        loadingButtonsDisabled: loadingButtons.slice(0, 3).every((item) => item.disabled),
        loadingStatus: loadingStatus.textContent,
        selections, pages, shortcuts,
        derivedMarker: container.children.find((item) => item.className === "health-comparison-details")
          .children.some((item) => item.className === "health-comparison-origin"),
      }));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script], cwd=ROOT,
        check=True, capture_output=True, text=True,
    )
    result = json.loads(completed.stdout)
    assert result["endpointValid"] is True
    assert result["endpointRejectsWrongAfter"] is False
    assert result["pairValid"] is True
    assert result["presetLabels"] == ["1D", "3D", "1W", "Custom"]
    assert result["selectedPreset"] == "true"
    assert result["customDisclosure"] == ["true", "health-comparison-custom-controls", False]
    assert result["beforeOptions"][1][0] == "assessment-before"
    assert result["afterOptions"][0][0] == "assessment-after"
    assert result["heading"] == "Before 2026-09-01 00:00:00 → After 2026-09-02 00:00:00 UTC · 1 day"
    assert result["headingTitle"] == "Before 2026-09-01T00:00:00.123Z · After 2026-09-02T02:00:00.123+02:00"
    assert result["liveRegionConfigured"] == ["status", "polite", "true"]
    assert result["liveRegionPreserved"] is True
    assert result["loadingButtonsDisabled"] is True
    assert "Resolving the selected interval against the latest assessment." in result["loadingStatus"]
    assert result["selections"] == [["before", "assessment-after"]]
    assert result["pages"] == [["before", 25]]
    assert result["shortcuts"] == [["1d"]]
    assert result["derivedMarker"] is False


def test_health_comparison_row_ranges_and_direct_pagination() -> None:
    script = r"""
      import {renderHealthComparison} from "./src/js/tdash-health.js";

      class Element {
        constructor(tagName) {
          this.tagName = tagName;
          this.children = [];
          this.listeners = {};
          this.parentNode = null;
        }
        appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
        replaceChildren() { this.children = []; }
        setAttribute(name, value) { this[name] = value; }
        addEventListener(name, listener) { this.listeners[name] = listener; }
      }
      globalThis.document = {createElement: (tagName) => new Element(tagName)};
      const find = (root, className) => {
        if (root.className === className) return root;
        for (const child of root.children) {
          const match = find(child, className);
          if (match) return match;
        }
        return null;
      };
      const row = (index) => ({
        itemId: `item-${index}`, scope: "device", subjectId: `device-${index}`,
        itemKind: "sample", sampleCount: 1, beforeValue: 1, afterValue: 2,
        delta: 1, unit: "count", comparable: true, change: "increased",
        sourceFiles: ["snapshot.json"], resetState: "known",
      });
      const makeComparison = (offset, size, filteredItemCount = 482, itemCount = 1626) => ({
        comparisonId: "pair", beforeObservedAt: "2026-10-01T00:00:00Z",
        afterObservedAt: "2026-10-02T00:00:00Z", elapsedSeconds: 86400,
        itemCount, filteredItemCount, offset, limit: 25,
        items: Array.from({length: size}, (_, index) => row(offset + index)),
        comparable: true, baselineState: "available", gapState: "within-policy",
        resetState: "known", reasons: [], origin: "stored",
      });
      const list = {total: 1, offset: 0, limit: 25, items: [{
        comparisonId: "pair", beforeObservedAt: "2026-10-01T00:00:00Z",
        afterObservedAt: "2026-10-02T00:00:00Z",
      }]};
      const requested = [];
      const render = (comparison, viewState = {}) => {
        const container = new Element("section");
        renderHealthComparison(container, list, comparison, {
          comparisonId: "pair", result: "changed", scope: "all", ...viewState,
        }, {items: (offset, action) => requested.push([offset, action])});
        return container;
      };
      const first = render(makeComparison(0, 25));
      const firstRange = find(first, "health-comparison-row-count").textContent;
      const firstTotal = find(first, "health-comparison-total-count").textContent;
      const firstPager = find(first, "health-comparison-row-pagination");
      const firstPage = firstPager.children[2];
      const firstActions = firstPager.children.map((control, index) => index === 2
        ? control.children.find((option) => option.value === control.value).textContent
        : control.textContent);
      firstPager.children[4].listeners.click();
      firstPage.value = "8";
      firstPage.listeners.change();

      const last = render(makeComparison(475, 7));
      const lastRange = find(last, "health-comparison-row-count").textContent;
      const lastPage = find(last, "health-comparison-row-pagination").children[2].value;
      find(last, "health-comparison-row-pagination").children[1].listeners.click();
      find(last, "health-comparison-row-pagination").children[0].listeners.click();
      const pending = render(makeComparison(0, 25), {itemsLoading: true});
      const pendingDisabled = find(pending, "health-comparison-row-pagination")
        .children.every((control) => control.disabled);
      const zero = render(makeComparison(0, 0, 0));
      const zeroRange = find(zero, "health-comparison-row-count").textContent;
      const zeroHasPager = Boolean(find(zero, "health-comparison-row-pagination"));
      const single = render(makeComparison(0, 25, 25, 1626));
      const singleDisabled = find(single, "health-comparison-row-pagination")
        .children.every((control) => control.disabled);
      console.log(JSON.stringify({
        firstRange, firstTotal, firstActions, firstPageCount: firstPage.children.length,
        lastRange, lastPage, requested, pendingDisabled, zeroRange, zeroHasPager, singleDisabled,
      }));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script], cwd=ROOT,
        check=True, capture_output=True, text=True,
    )
    result = json.loads(completed.stdout)
    assert result == {
        "firstRange": "1–25 of 482 matching rows",
        "firstTotal": "1,626 total rows",
        "firstActions": ["First", "Previous", "Page 1 of 20", "Next", "Last"],
        "firstPageCount": 20,
        "lastRange": "476–482 of 482 matching rows",
        "lastPage": "20",
        "requested": [[475, "last"], [175, "page"], [450, "previous"], [0, "first"]],
        "pendingDisabled": True,
        "zeroRange": "0 matching rows",
        "zeroHasPager": False,
        "singleDisabled": True,
    }


def test_comparison_presets_stay_latest_anchored_and_disclosures_keep_focus() -> None:
    script = r"""
      import {renderHealthComparison} from "./src/js/tdash-health.js";

      class Element {
        constructor(tagName) {
          this.tagName = tagName;
          this.children = [];
          this.listeners = {};
          this.parentNode = null;
        }
        appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
        replaceChildren() {
          this.children.forEach((child) => { child.parentNode = null; });
          this.children = [];
        }
        remove() {
          if (!this.parentNode) return;
          this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
          this.parentNode = null;
        }
        setAttribute(name, value) { this[name] = value; }
        getAttribute(name) { return this[name] ?? null; }
        addEventListener(name, listener) { this.listeners[name] = listener; }
        focus() { globalThis.document.activeElement = this; }
        querySelectorAll(selector) {
          const matches = (element) => selector === "button[aria-controls]"
            ? element.tagName === "button" && element.getAttribute("aria-controls")
            : selector === "[data-comparison-page-action]"
              ? Boolean(element.getAttribute("data-comparison-page-action"))
              : false;
          const result = [];
          const visit = (element) => element.children.forEach((child) => {
            if (matches(child)) result.push(child);
            visit(child);
          });
          visit(this);
          return result;
        }
      }
      globalThis.document = {activeElement: null, createElement: (tagName) => new Element(tagName)};
      const find = (root, className) => {
        if (root.className === className) return root;
        for (const child of root.children) {
          const match = find(child, className);
          if (match) return match;
        }
        return null;
      };
      const before = {assessmentId: "before", observedAt: "2026-10-01T00:00:00Z",
        assessedAt: "2026-10-01T00:01:00Z", completeness: "complete"};
      const latest = {assessmentId: "latest", observedAt: "2026-10-02T00:00:00Z",
        assessedAt: "2026-10-02T00:01:00Z", completeness: "complete"};
      const historical = {assessmentId: "historical", observedAt: "2026-09-10T00:00:00Z",
        assessedAt: "2026-09-10T00:01:00Z", completeness: "complete"};
      const latestPresetPage = {shortcuts: [
        {interval: "1d", candidate: before},
        {interval: "3d", candidate: before},
        {interval: "1w", candidate: before},
      ]};
      const endpointPages = {
        before: {offset: 0, limit: 25, total: 2, items: [before, historical], selected: before},
        after: {offset: 0, limit: 25, total: 2, items: [historical, latest],
          selected: historical, shortcuts: []},
      };
      const comparison = {
        comparisonId: "pair", beforeAssessmentId: "before", afterAssessmentId: "latest",
        beforeObservedAt: before.observedAt, afterObservedAt: latest.observedAt,
        elapsedSeconds: 86400, itemCount: 0, filteredItemCount: 0,
        limit: 25, offset: 0, items: [], comparable: false, resetState: "unknown",
        baselineState: "available", gapState: "within-policy", reasons: ["reset-unknown"],
        origin: "derived", createdAt: null,
      };
      const viewState = {
        endpointSelection: true, latestPresetPage, endpointPages,
        endpointLoading: {before: false, after: false}, endpointErrors: {before: "", after: ""},
        before, after: latest, beforeAssessmentId: "before", afterAssessmentId: "latest",
        intent: "1d", customOpen: false, detailsOpen: false, scope: "all", result: "changed",
      };
      const requestedPresets = [];
      const selectedEndpoints = [];
      const container = new Element("section");
      const actions = {
        preset: (interval) => requestedPresets.push(interval),
        endpointSelect: (side, id) => selectedEndpoints.push([side, id]),
        customOpen: () => {},
        detailsOpen: () => {},
      };
      renderHealthComparison(container, null, comparison, viewState, actions);
      const controls = find(container, "health-comparison-controls");
      const presetButtons = controls.children[0].children.filter((element) => element.tagName === "button");
      const custom = presetButtons[3];
      const customControls = find(container, "health-comparison-custom");
      const closedHasSelectors = Boolean(find(customControls, "health-comparison-endpoint-control"));
      presetButtons[1].listeners.click();
      document.activeElement = custom;
      viewState.customOpen = true;
      renderHealthComparison(container, null, comparison, viewState, actions);
      const reopenedControls = find(container, "health-comparison-controls");
      const reopenedCustom = reopenedControls.children[0].children
        .filter((element) => element.tagName === "button")[3];
      const openedCustomControls = find(container, "health-comparison-custom");
      const customFocusRestored = document.activeElement === reopenedCustom;
      const filterRow = find(container, "health-comparison-filter-row");
      const detailToggle = container.children.find((element) => element.textContent === "Details");
      document.activeElement = detailToggle;
      viewState.detailsOpen = true;
      renderHealthComparison(container, null, comparison, viewState, actions);
      const expandedDetailsToggle = container.children.find((element) => element.textContent === "Details");
      const expandedDetails = find(container, "health-comparison-details");
      const status = container.children.find((element) => element.className === "health-comparison-primary-status");
      console.log(JSON.stringify({
        candidateButtonsEnabled: presetButtons.slice(0, 3).every((button) => !button.disabled),
        selectedIntent: presetButtons.slice(0, 3).map((button) => button["aria-pressed"]),
        customDisclosure: [custom["aria-expanded"], custom["aria-pressed"], customControls.hidden, closedHasSelectors],
        customReopened: [reopenedCustom["aria-expanded"], openedCustomControls.hidden,
          Boolean(find(openedCustomControls, "health-comparison-endpoint-control")),
          customFocusRestored],
        requestedPresets,
        filterOrder: filterRow.children.slice(0, 2).map((select) => select["aria-label"]),
        summary: find(container, "health-comparison-pair-summary").textContent,
        status: status.textContent,
        detailsExpanded: [expandedDetailsToggle["aria-expanded"], expandedDetails.hidden,
          document.activeElement === expandedDetailsToggle,
          expandedDetails.children.some((element) => element.className === "health-comparison-origin")],
        selectedEndpoints,
      }));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script], cwd=ROOT,
        check=True, capture_output=True, text=True,
    )
    result = json.loads(completed.stdout)
    assert result == {
        "candidateButtonsEnabled": True,
        "selectedIntent": ["true", "false", "false"],
        "customDisclosure": ["false", "false", True, False],
        "customReopened": ["true", False, True, True],
        "requestedPresets": ["3d"],
        "filterOrder": ["Comparison scope", "Result"],
        "summary": "Before 2026-10-01 00:00:00 → After 2026-10-02 00:00:00 UTC · 1 day",
        "status": "Unknown",
        "detailsExpanded": ["true", False, True, True],
        "selectedEndpoints": [],
    }


def test_off_page_shortcut_candidate_remains_available_while_before_page_loads() -> None:
    script = r"""
      import {findHealthComparisonEndpointMetadata} from "./src/js/tdash-health.js";

      const shortcutCandidate = {
        assessmentId: "assessment-off-page",
        observedAt: "2026-09-01T00:00:00Z",
        assessedAt: "2026-09-01T00:01:00Z",
        completeness: "partial",
      };
      const pages = {
        before: {items: [], selected: null},
        after: {items: [{assessmentId: "assessment-new-after",
          observedAt: "2026-09-03T00:00:00Z"}]},
      };
      const before = findHealthComparisonEndpointMetadata(
        shortcutCandidate.assessmentId, pages, null, shortcutCandidate,
      );
      const after = findHealthComparisonEndpointMetadata(
        "assessment-new-after", pages, null, shortcutCandidate,
      );
      console.log(JSON.stringify({
        selectedBefore: before?.assessmentId,
        preserveBefore: Boolean(before?.observedAt && after?.observedAt
          && Date.parse(before.observedAt) < Date.parse(after.observedAt)),
      }));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script], cwd=ROOT,
        check=True, capture_output=True, text=True,
    )

    assert json.loads(completed.stdout) == {
        "selectedBefore": "assessment-off-page",
        "preserveBefore": True,
    }


def test_health_requests_resolve_relative_to_direct_and_proxy_dashboard_paths() -> None:
    script = r"""
      import {
        fetchHealthAssessment,
        fetchHealthDevice,
        fetchHealthComparison,
        fetchHealthSupport,
        startHealthProcessing,
        fetchHealthJob,
        cancelHealthJob,
      } from "./src/js/tdash-health.js";

      const requested = [];
      globalThis.fetch = async (path) => {
        requested.push(path);
        return { ok: true, json: async () => ({}) };
      };

      await fetchHealthAssessment("dataset-id");
      await fetchHealthDevice("assessment-id", "extaddr:0011223344556677");
      await fetchHealthComparison("comparison:one", 0, undefined, {
        scope: "all", result: "changed",
      });
      await fetchHealthSupport("extpan:0011223344556677");
      await startHealthProcessing("dataset-id");
      await fetchHealthJob("job-id");
      await cancelHealthJob("job-id");

      const pageUrls = [
        "http://localhost:9165/tdash.html",
        "https://ha.example/api/hassio_ingress/session/tdash.html",
      ];
      console.log(JSON.stringify({
        requested,
        resolved: pageUrls.map((base) => requested.map((path) => new URL(path, base).href)),
      }));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert len(result["requested"]) == 8
    assert all(path.startswith("api/") for path in result["requested"])
    assert all(url.startswith("http://localhost:9165/api/") for url in result["resolved"][0])
    assert all(
      url.startswith("https://ha.example/api/hassio_ingress/session/api/")
        for url in result["resolved"][1]
    )


def test_roster_request_pins_assessment_and_bounded_query() -> None:
    script = r"""
      import {fetchHealthRoster} from "./src/js/tdash-health.js";
      let url;
      globalThis.fetch = async (path) => {
        url = path;
        return {ok: true, json: async () => ({schemaVersion: 2})};
      };
      await fetchHealthRoster("extpan:78b9775b001c1cbe", "assessment-1", {
        offset: 25, search: "Office Router", presence: "missing", rosterState: "expected",
        sort: {column: "lastObserved", direction: "descending"},
      });
      console.log(JSON.stringify(Object.fromEntries(new URL(url, "http://localhost/").searchParams)));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script], cwd=ROOT,
        check=True, capture_output=True, text=True,
    )
    assert json.loads(completed.stdout) == {
        "network": "extpan:78b9775b001c1cbe", "assessment": "assessment-1",
        "limit": "25", "offset": "25", "q": "Office Router", "presence": "missing",
        "rosterState": "expected", "sort": "lastObserved", "direction": "descending",
    }


def test_health_sections_use_stored_status_and_evidence_kind_without_reclassification() -> None:
    script = r"""
      import {projectHealthFindingSections} from "./src/js/tdash-health.js";
      const groups = [
        {ruleId: "poor.rule", status: "poor", scope: "device", findings: [{evidenceKind: "snapshot"}]},
        {ruleId: "unknown.rule", status: "unknown", scope: "network", findings: [{evidenceKind: "historical"}]},
        {ruleId: "moderate.rule", status: "moderate", scope: "relationship", findings: [{evidenceKind: "snapshot"}]},
        {ruleId: "strong.rule", status: "strong", scope: "device", findings: [{evidenceKind: "snapshot"}]},
      ];
      const sections = projectHealthFindingSections(groups, {
        status: "all", scope: "all", evidenceKind: "snapshot",
      });
      console.log(JSON.stringify(sections.map(({id, groups: items}) => ({
        id, rules: items.map(({ruleId, status}) => [ruleId, status]),
      }))));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == [
        {"id": "needs-work", "rules": [["poor.rule", "poor"]]},
        {"id": "needs-attention", "rules": [["moderate.rule", "moderate"]]},
        {"id": "going-well", "rules": [["strong.rule", "strong"]]},
    ]


def test_external_routing_is_excluded_from_health_presentation_projections() -> None:
    script = r"""
      import {
        projectHealthFindingDetail,
        projectHealthFindingSections,
        projectHealthSummaryRows,
        projectVisibleHealthFindingGroups,
        reconcileHealthInsightsSelection,
      } from "./src/js/tdash-health.js";

      const finding = (findingId, evidenceKind = "snapshot") => ({
        findingId, rank: 1, evidenceKind, materiality: "network",
        deviceIds: ["extaddr:1"], relationshipIds: [], endpoints: [], evidence: {},
      });
      const external = {
        groupId: "external", ruleId: "network.external-routing", status: "moderate",
        scope: "external", title: "Border Router OMR Addressing", summary: "Hidden",
        confidence: "medium", count: 1, deviceIds: ["extaddr:1"], relationshipIds: [],
        findings: [finding("external-finding")],
      };
      const retained = {
        groupId: "retained", ruleId: "network.router-redundancy", status: "poor",
        scope: "network", title: "Router Redundancy", summary: "Visible",
        confidence: "high", count: 1, deviceIds: [], relationshipIds: [],
        findings: [finding("retained-finding")],
      };
      const assessment = { assessmentId: "assessment", findingGroups: [external, retained] };
      console.log(JSON.stringify({
        visible: projectVisibleHealthFindingGroups(assessment.findingGroups).map(({ ruleId }) => ruleId),
        rows: projectHealthSummaryRows(assessment.findingGroups, { view: "all" }).map(({ ruleId }) => ruleId),
        sections: projectHealthFindingSections(assessment.findingGroups).flatMap(
          ({ groups }) => groups.map(({ ruleId }) => ruleId),
        ),
        detail: projectHealthFindingDetail(external),
        cleared: reconcileHealthInsightsSelection({ selectedGroupId: "external", selectedFindingId: "external-finding" }, assessment),
        retained: reconcileHealthInsightsSelection({ selectedGroupId: "retained", selectedFindingId: "retained-finding" }, assessment),
      }));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(completed.stdout)
    assert result["visible"] == ["network.router-redundancy"]
    assert result["rows"] == ["network.router-redundancy"]
    assert result["sections"] == ["network.router-redundancy"]
    assert result["detail"] is None
    assert result["cleared"]["selectedGroupId"] is None
    assert result["cleared"]["detailsOpen"] is False
    assert result["retained"]["selectedGroupId"] == "retained"
    assert result["retained"]["selectedFindingId"] == "retained-finding"


def test_health_summary_projection_sort_counts_and_selection_reconciliation() -> None:
    script = r"""
      import {
        projectHealthFindingDetail,
        projectHealthSummaryRows,
        reconcileHealthInsightsSelection,
        toggleHealthFindingSelection,
      } from "./src/js/tdash-health.js";
      const finding = (findingId, overrides = {}) => ({
        findingId,
        rank: 10,
        evidenceKind: "snapshot",
        materiality: "device",
        deviceIds: [],
        relationshipIds: [],
        endpoints: [],
        evidence: {value: 1},
        whyItMatters: "Impact",
        action: "Act",
        verify: "Verify",
        sourceFiles: ["source.json"],
        ...overrides,
      });
      const groups = [
        {
          groupId: "moderate-device", ruleId: "device.rule", status: "moderate",
          scope: "device", title: "Device issue", summary: "Summary", confidence: "high",
          count: 2, deviceIds: ["extaddr:2", "extaddr:1"], relationshipIds: [],
          findings: [finding("finding-1", {deviceIds: ["extaddr:1"]})],
        },
        {
          groupId: "poor-link", ruleId: "relationship.rule", status: "poor",
          scope: "relationship", title: "Link issue", summary: "Summary", confidence: "medium",
          count: 3, deviceIds: ["extaddr:1", "extaddr:2"], relationshipIds: ["link:1", "link:2"],
          findings: [finding("finding-2", {
            evidenceKind: "historical", materiality: "relationship",
            relationshipIds: ["link:1", "link:2"], whyItMatters: "Link impact",
          })],
        },
        {
          groupId: "strong-network", ruleId: "network.rule", status: "strong",
          scope: "network", title: "Network good", summary: "Summary", confidence: "high",
          count: 1, deviceIds: [], relationshipIds: [],
          findings: [finding("finding-3", {materiality: "network"})],
        },
      ];
      const actionable = projectHealthSummaryRows(groups);
      const all = projectHealthSummaryRows(groups, {view: "all"});
      const detail = projectHealthFindingDetail(groups[1], "finding-2");
      const affectedGroup = {
        ...groups[1],
        findings: [
          finding("affected-1", {
            summary: "Device A has one observed parent", deviceIds: ["extaddr:1"],
            endpoints: [{deviceId: "extaddr:1", displayName: "Device A"}],
          }),
          finding("affected-2", {
            summary: "Summary", deviceIds: ["extaddr:2"],
            endpoints: [{deviceId: "extaddr:2", displayName: "Device B"}],
          }),
          finding("affected-3", {
            summary: "Repeated item summary", deviceIds: ["extaddr:3"],
            endpoints: [{deviceId: "extaddr:3", displayName: "Device C"}],
          }),
          finding("affected-4", {
            summary: "Repeated item summary", deviceIds: ["extaddr:4"],
            endpoints: [{deviceId: "extaddr:4", displayName: "Device D"}],
          }),
        ],
      };
      const highlights = projectHealthFindingDetail(affectedGroup);
      const selectedDetail = projectHealthFindingDetail(affectedGroup, "affected-2");
      const retained = reconcileHealthInsightsSelection({
        assessmentId: "old", selectedGroupId: "poor-link",
        selectedFindingId: "finding-2", detailsOpen: true,
      }, {assessmentId: "new", findingGroups: groups});
      const removedFinding = reconcileHealthInsightsSelection({
        assessmentId: "old", selectedGroupId: "poor-link",
        selectedFindingId: "removed-finding", detailsOpen: true,
      }, {assessmentId: "new", findingGroups: groups});
      const cleared = reconcileHealthInsightsSelection({
        selectedGroupId: "missing", selectedFindingId: "missing", detailsOpen: true,
      }, {assessmentId: "new", findingGroups: groups});
      console.log(JSON.stringify({
        actionable: actionable.map((row) => [row.groupId, row.affected.label]),
        all: all.map((row) => row.groupId),
        detail: [detail.affected.label, detail.items[0].isExpanded, detail.shared.action],
        highlights: {
          expanded: highlights.items.map(({isExpanded}) => isExpanded),
          summaries: highlights.items.map(({highlightSummary}) => highlightSummary),
          selected: selectedDetail.items.map(({isExpanded}) => isExpanded),
        },
        toggles: [
          toggleHealthFindingSelection(null, "affected-1"),
          toggleHealthFindingSelection("affected-1", "affected-1"),
          toggleHealthFindingSelection("affected-1", "affected-2"),
        ],
        retained,
        removedFinding,
        cleared,
      }));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(completed.stdout)
    assert result["actionable"] == [
        ["poor-link", "2 relationships"],
        ["moderate-device", "2 devices"],
    ]
    assert result["all"] == ["poor-link", "moderate-device", "strong-network"]
    assert result["detail"] == ["2 relationships", True, "Act"]
    assert result["highlights"]["expanded"] == [False, False, False, False]
    assert result["highlights"]["summaries"] == [
      "Device A has one observed parent", None, None, None,
    ]
    assert result["highlights"]["selected"] == [False, True, False, False]
    assert result["toggles"] == ["affected-1", None, "affected-2"]
    assert result["retained"]["assessmentId"] == "new"
    assert result["retained"]["selectedFindingId"] == "finding-2"
    assert result["removedFinding"]["selectedGroupId"] == "poor-link"
    assert result["removedFinding"]["selectedFindingId"] is None
    assert result["removedFinding"]["detailsOpen"] is True
    assert result["cleared"]["selectedGroupId"] is None
    assert result["cleared"]["detailsOpen"] is False


def test_health_status_summary_is_informational_not_a_coloring_control() -> None:
    script = r'''
      import { renderHealthStatus } from "./src/js/tdash-health.js";

      class Element {
        constructor(tagName) {
          this.tagName = tagName;
          this.children = [];
          this.attributes = {};
          this.listeners = {};
          this.textContent = "";
          this.className = "";
        }
        appendChild(child) { this.children.push(child); return child; }
        replaceChildren(...children) { this.children = children; }
        toggleAttribute(name, force) { this.attributes[name] = String(Boolean(force)); }
        setAttribute(name, value) { this.attributes[name] = String(value); }
        addEventListener(type, listener) { this.listeners[type] = listener; }
        click() { this.listeners.click?.(); }
      }
      globalThis.document = { createElement: (tagName) => new Element(tagName) };

      const container = new Element("div");
      let toggledColoring = 0;
      renderHealthStatus(container, {
        assessment: {
          status: "Moderate", completeness: "complete", observedAt: "2026-09-18T00:00:00Z",
        },
        loading: false, error: "", refreshStatus: "", topologyColoringEnabled: false,
      });
      const [heading, status] = container.children;
      status.click();
      console.log(JSON.stringify({
        heading: [heading.tagName, heading.textContent],
        status: [status.tagName, status.textContent, status.className, status.attributes["aria-pressed"] ?? null],
        toggledColoring,
      }));
    '''
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(completed.stdout)
    assert result["heading"] == ["span", "Health:"]
    assert result["status"] == [
      "span",
      "Moderate",
      "health-status-state state-moderate",
      None,
    ]
    assert result["toggledColoring"] == 0


def test_health_workflow_controls_and_navigation_contract_are_present() -> None:
    html = (ROOT / "src/tdash.html").read_text(encoding="utf-8")
    health_js = (ROOT / "src/js/tdash-health.js").read_text(encoding="utf-8")
    ui_js = (ROOT / "src/js/tdash-ui.js").read_text(encoding="utf-8")
    table_js = (ROOT / "src/js/tdash-table-renderer.js").read_text(encoding="utf-8")
    topology_js = (ROOT / "src/js/tdash-topology-renderer.js").read_text(encoding="utf-8")
    css = (ROOT / "src/tdash.css").read_text(encoding="utf-8")

    for element_id in (
          "health-view-filter",
      "health-status-filter",
      "health-scope-filter",
      "health-evidence-filter",
      "btn-health-return",
      "btn-health-reset",
      "btn-health-refresh",
      "btn-health-refresh-cancel",
          "health-insights-summary",
          "health-finding-table",
          "health-insights-announcement",
          "health-finding-details",
          "btn-health-finding-close",
    ):
      assert f'id="{element_id}"' in html
    for section in ("Needs Work", "Needs Attention", "Going Well"):
      assert section in health_js
    for action in (
      "showTopology",
      "showTable",
      "inspectDevice",
      "compareEndpoints",
      "applyFilter",
    ):
      assert action in health_js
      assert action in ui_js
    assert "restoreHealthNavigationContext" in ui_js
    assert "healthComparisonDetailController.retrySelected()" in ui_js
    assert "retryDetail: () => { void healthComparisonDetailController.retrySelected(); }" in ui_js
    assert "comparisonTableScrollTop: healthInsightsViewState.comparisonTableScrollTop" in ui_js
    assert 'event.target?.matches?.(".health-comparison-table-wrap")' in ui_js
    assert "healthInsightsViewState.comparisonTableScrollTop = event.target.scrollTop;" in ui_js
    assert "updatedComparisonWrap.scrollTop = healthInsightsViewState.comparisonTableScrollTop;" in ui_js
    assert "renderHealthFindingDetails" in ui_js
    assert "toggleHealthFindingSelection" in ui_js
    assert "initContextDetailsPanel" in ui_js
    assert 'tableRow.addEventListener("click", () => actions.selectGroup?.(row.groupId));' in health_js
    assert 'aria-current", "true"' in health_js
    assert 'heading.setAttribute("aria-sort"' in health_js
    assert "invalidateHealthRefresh" in ui_js
    assert "Health: refreshing" in health_js
    assert "Health: failed" in health_js
    assert "Health: cancelled" in health_js
    assert "HEALTH_COLORING_PREFERENCE_KEY" in ui_js
    assert "healthColoringPreferenceSet" in ui_js
    assert "enableHealthColoringOnFirstInsightsVisit" in ui_js
    assert 'currentView !== "insights"' in ui_js
    assert 'selectedFindingId = null;' in ui_js
    assert "setTopologyHealthFindings(findings, healthTopologyColoringEnabled && matchingAssessment !== null)" in ui_js
    assert "applyHealthAssessmentPresentation(assessment)" in ui_js
    assert "applyHealthAssessmentPresentation(null)" in ui_js
    assert "HEALTH_BACKGROUND_COLORS" in topology_js
    assert "background: HEALTH_BACKGROUND_COLORS[status]" in topology_js
    view_toolbar = html.split('<div class="view-toggle-bar">', 1)[1].split(
      '<div id="view-status-line-panel"', 1,
    )[0]
    assert 'id="btn-health-coloring"' in view_toolbar
    assert 'id="btn-health-columns"' in view_toolbar
    assert "coloringButton.hidden = currentView !== \"topology\" || !healthEligible" in ui_js
    assert "columnsButton.hidden = currentView !== \"table\" || !healthEligible" in ui_js
    render_current_view_start = ui_js.index("function renderCurrentView(")
    render_current_view_end = ui_js.index("function getPhysicsProfileSelect", render_current_view_start)
    render_current_view = ui_js[render_current_view_start:render_current_view_end]
    assert "updateHealthPresentationControls();" in render_current_view
    assert 'aria-controls", detailId' in health_js
    assert "details.hidden = !item.isExpanded;" in health_js
    assert "health-affected-chevron" in health_js
    detail_renderer = health_js[health_js.index("export function renderHealthFindingDetails"):]
    assert detail_renderer.index('"health-finding-detail-summary"') < detail_renderer.index(
      '"health-finding-detail-priority"'
    )
    assert detail_renderer.index('"Recommended action"') < detail_renderer.index('"Investigate"')
    assert detail_renderer.index('"Investigate"') < detail_renderer.index('"Affected items"')
    assert ".health-finding-detail-priority" in css
    assert '.health-affected-select[aria-expanded="true"] .health-affected-chevron' in css
    assert '<option value="all" selected>All</option>' in html
    assert 'view: "all"' in ui_js
    assert 'healthInsightsViewState.view = "all";' in ui_js
    assert 'if (viewFilter) viewFilter.value = "all";' in ui_js
    assert "Health processed:" in health_js
    assert "refreshedAt" in ui_js
    assert html.index('id="btn-health-refresh"') < html.index('id="btn-details-panel-toggle"')
    assert 'lastRenderedDatasetByView.delete("table")' in ui_js
    assert 'lastRenderedDatasetByView.delete("topology")' in ui_js
    assert "setTopologyHealthFindings" in ui_js
    assert "setTableHealthFindings" in ui_js
    assert 'replace(/^extAddress:/, "extaddr:")' in table_js
    assert 'replace(/^extAddress:/, "extaddr:")' in topology_js
    assert "viewModel.rawByIdForDetails.get(nodeId)" in topology_js
    assert "visibleHealthColumns" in table_js
    assert "setTableHealthColumnsEnabled" in table_js
    assert '"Dataset Evidence Pillars"' in health_js
    assert "COVERAGE_STATUS_GLYPHS" in health_js
    assert 'sufficient: "\\u2713"' in health_js
    assert 'limited: "!"' in health_js
    assert 'missing: "\\u00d7"' in health_js
    assert 'if (capability !== status)' in health_js
    assert 'Dataset capability: ${capability}.' in health_js
    assert ".health-coverage-heading" in css
    assert ".health-finding-evidence" in css
    assert ".health-coverage-pillar" in css
    assert ".health-coverage-state.state-sufficient" in css
    assert ".health-coverage-state.state-limited" in css
    assert ".health-coverage-state.state-missing" in css
    assert ".health-status-button" not in css
    assert ".health-status-navigation" not in css
    assert 'id="btn-health-coloring"' in html
    assert 'id="btn-health-columns"' in html
    assert 'aria-pressed="false"' in html
    assert "overflow-wrap: anywhere" in css
    assert "@media (max-width: 760px)" in css


def test_comparison_reset_and_return_preserve_health_tab_context() -> None:
    ui_js = (ROOT / "src/js/tdash-ui.js").read_text(encoding="utf-8")
    comparison_reset = ui_js.split("function resetHealthComparison() {", 1)[1].split(
        "\nfunction resetHealthWorkflow()", 1,
    )[0]
    state_reset = ui_js.split("function resetHealthComparisonState() {", 1)[1].split(
        "\nfunction resetHealthComparison()", 1,
    )[0]

    assert 'healthInsightsTab === "comparison" && currentView === "insights"' in comparison_reset
    assert "resetHealthComparisonState();" in comparison_reset
    assert "ensureHealthComparisonLoaded();" in comparison_reset
    assert "switchView(" not in comparison_reset
    assert "healthInsightsState.comparisonListRequestVersion += 1;" in state_reset
    assert "healthComparisonDetailController.invalidate();" in state_reset
    assert "resetComparisonEndpointState();" in state_reset
    assert "healthInsightsTab !== \"findings\"" in ui_js
    assert 'addEventListener("click", resetHealthComparison)' in ui_js
    assert "healthTab: healthInsightsTab" in ui_js
    assert "healthInsightsTab = context.healthTab ?? HEALTH_INSIGHTS_TABS[0].id;" in ui_js
    assert "healthInsightsTab = HEALTH_INSIGHTS_TABS[0].id;" in ui_js
    assert "savedInsights[key] = healthInsightsViewState[key];" in ui_js
    assert "comparisonResetPendingRefresh = healthInsightsState.loading;" in ui_js
    assert "if (resetComparisonDuringRefresh && healthInsightsTab === \"comparison\")" in ui_js
