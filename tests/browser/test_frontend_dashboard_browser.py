import re

import pytest

pytestmark = pytest.mark.browser


def topology(dashboard, expected_nodes=2):
    page = dashboard.page
    page.wait_for_function("""expected => new RegExp(
      `^${expected} nodes \\\\| \\\\d+ links`).test(
        document.querySelector('#view-status-line-content').textContent)""", arg=expected_nodes)
    page.wait_for_function("""() => {
      const canvas = document.querySelector('#topology-canvas-wrap canvas');
      if (!canvas || canvas.width <= 0 || canvas.height <= 0 ||
          canvas.getBoundingClientRect().width <= 0 || canvas.getBoundingClientRect().height <= 0)
        return false;
      const scratch = document.createElement('canvas');
      scratch.width = canvas.width; scratch.height = canvas.height;
      const context = scratch.getContext('2d', {willReadFrequently: true});
      context.drawImage(canvas, 0, 0);
      const pixels = context.getImageData(0, 0, scratch.width, scratch.height).data;
      for (let i = 4; i < pixels.length; i += 4)
        if (pixels[i] !== pixels[0] || pixels[i + 1] !== pixels[1] ||
            pixels[i + 2] !== pixels[2] || pixels[i + 3] !== pixels[3]) return true;
      return false;
    }""")
    return page.locator("#view-status-line-content").inner_text()


def test_actual_rendering_filters_selection_and_theme(dashboard):
    page = dashboard.page
    dashboard.sync()
    baseline = topology(dashboard)
    dashboard.sync()
    assert topology(dashboard) == baseline
    assert page.locator("#topology-canvas-wrap canvas").count() == 1
    for theme in ["dark", "light"]:
        page.evaluate("theme => window.tdashTheme.setPreference(theme)", theme)
        assert topology(dashboard) == baseline
    dashboard.select("#node-filter", "border-routers")
    topology(dashboard, 1)
    dashboard.select("#node-filter", "all")
    assert topology(dashboard) == baseline
    dashboard.select("#link-filter", "lq_high")
    assert topology(dashboard).startswith("2 nodes | 1 links | Filtered")
    dashboard.select("#link-filter", "default_links")
    assert topology(dashboard) == baseline
    dashboard.select("#diagnostic-source-filter", "macCounters")
    dashboard.select("#diagnostic-filter", "mac-total-errors-ratio-high")
    topology(dashboard, 1)
    assert page.evaluate("""() => window.tdashDebug.getVisNetwork().body.data.nodes
      .get().filter(node => !node.hidden).map(node => node.id)""") == ["0x1000"]
    dashboard.select("#diagnostic-filter", "all")
    dashboard.select("#diagnostic-source-filter", "macCounters")
    assert topology(dashboard) == baseline
    dashboard.active["filter"] = "search:aa00000000000001"
    page.locator("#search-input").fill("aa00000000000001")
    page.locator("#search-input").press("Enter")
    page.wait_for_function("() => /Filtered/.test("
                          "document.querySelector('#view-status-line-content').textContent)")
    page.locator("#btn-view-status-details").click()
    page.wait_for_function("() => /1 of 2 rows match/.test("
                          "document.querySelector('#view-status-details-popover').textContent)")
    page.locator("#btn-view-status-details-close").click()
    page.locator("#btn-search-clear").evaluate("(button) => button.click()")
    assert topology(dashboard) == baseline
    assert page.locator(
        "#node-filter, #link-filter, #diagnostic-source-filter, #diagnostic-filter"
    ).evaluate_all("elements => elements.map(element => element.value)") == [
        "all", "default_links", "macCounters", "all",
    ]
    dashboard.active["filter"] = "all"
    page.evaluate("""() => {
      window.__resolvedSelections = [];
      document.addEventListener('tdash:device-selected', event => {
        if (event.detail.resolved) window.__resolvedSelections.push(event.detail.record?.extAddress);
      });
    }""")
    position = page.evaluate("""async () => {
      const renderer = await import('/js/tdash-topology-renderer.js');
      const network = renderer.getVisNetwork();
      network.stopSimulation();
      const id = network.body.data.nodes.getIds()[0];
      return network.canvasToDOM(network.getPositions([id])[id]);
    }""")
    box = page.locator("#topology-canvas-wrap canvas").bounding_box()
    page.mouse.click(box["x"] + position["x"], box["y"] + position["y"])
    page.wait_for_function("() => window.__resolvedSelections.length > 0")
    page.wait_for_function("() => document.querySelector('#device-extaddress').textContent.trim() !== ''")
    assert page.evaluate("window.__resolvedSelections") == ["aa00000000000001"]
    for theme in ["dark", "light"]:
        page.evaluate("theme => window.tdashTheme.setPreference(theme)", theme)
        assert topology(dashboard) == baseline
        assert page.evaluate(
            "() => window.tdashDebug.getVisNetwork().getSelectedNodes()") == ["0x1000"]
    dashboard.view("table")
    assert page.locator("#data-table tbody tr").count() == 2
    assert page.locator("#data-table thead th").count() > 0
    page.evaluate("window.__resolvedSelections = []")
    page.locator("#data-table tbody tr").last.click()
    assert page.evaluate("window.__resolvedSelections") == ["aa00000000000002"]
    assert page.locator("#data-table tr.selected-row").count() == 1
    assert page.evaluate("""() => {
      const wrap = document.querySelector('#view-table .table-wrap');
      return wrap.clientWidth > 0 && wrap.scrollWidth >= wrap.clientWidth &&
        document.documentElement.scrollWidth <= window.innerWidth;
    }""")
    dashboard.view("thread-network-summary")
    page.wait_for_function("() => document.querySelector('#thread-network-content').textContent"
                          ".includes('Browser fixture')")
    dashboard.view("table")
    assert page.locator("#data-table tbody tr").count() == 2
    dashboard.view("topology")
    assert topology(dashboard) == baseline
    dashboard.choose("otbr-restapi", "otbr_restapi_devices_list")
    dashboard.sync()
    topology(dashboard, 1)


def test_failed_empty_refresh_and_cancel_preserve_accepted_view(dashboard):
    page = dashboard.page
    dashboard.sync()
    baseline = topology(dashboard)
    dashboard.mode = "error"
    dashboard.sync()
    assert re.search(r"Error|could not load|failed", page.locator(
        "#fetch-status-line-content").inner_text(), re.I)
    assert topology(dashboard) == baseline.replace(
        " | Network", " | Sync failed; retained data | Network")
    dashboard.mode = "normal"
    dashboard.sync()
    assert topology(dashboard) == baseline
    dashboard.mode = "async"
    page.clock.install()
    page.evaluate("window.__holdPoll = true")
    page.locator("#btn-fetch").evaluate("(button) => button.click()")
    page.wait_for_function("() => !document.querySelector('#btn-fetch-cancel').disabled")
    page.clock.run_for(2000)
    page.wait_for_function("() => window.__pollBodyWaiting === true")
    page.locator("#btn-fetch-cancel").evaluate("(button) => button.click()")
    page.evaluate("() => { window.__holdPoll = false; window.__releasePoll(); }")
    dashboard.settled()
    assert dashboard.deleted == ["fixture-job"]
    assert topology(dashboard) == baseline
    dashboard.mode = "empty"
    dashboard.sync()
    page.wait_for_function("() => /0 nodes|No (devices|data|nodes)|empty/i.test("
                          "document.querySelector('#view-status-line-content').textContent)")
    dashboard.mode = "normal"
    dashboard.sync()
    assert topology(dashboard) == baseline


def test_actual_adaptor_error_clears_old_canvas(dashboard):
    page = dashboard.page
    dashboard.sync()
    topology(dashboard)
    dashboard.mode = "malformed"
    dashboard.sync()
    page.wait_for_function("() => /Topology error: Cannot convert object to primitive value/.test("
                          "document.querySelector('#view-status-line-content').textContent)")
    assert page.locator("#topology-canvas-wrap canvas").count() == 0
    dashboard.mode = "normal"
    dashboard.sync()
    topology(dashboard)


def test_labels_stale_body_and_operations_cleanup(dashboard):
    page = dashboard.page
    dashboard.sync()
    dashboard.view("table")
    rows = page.locator("#data-table tbody tr")
    page.evaluate("window.__heldLabel = 'aa00000000000001'")
    rows.first.click()
    page.locator("#btn-device-details-settings").evaluate("(button) => button.click()")
    page.wait_for_function("() => window.__labelBodyWaiting === true")
    rows.last.click()
    page.locator("#btn-device-details-settings").evaluate("(button) => button.click()")
    page.wait_for_function("() => !document.querySelector('#device-label').disabled")
    page.evaluate("() => { window.__heldLabel = null; window.__releaseLabel(); }")
    page.locator("#device-label").fill("Updated peer")
    page.locator("#btn-device-settings-save").click()
    page.wait_for_function("() => /saved|added/i.test("
                          "document.querySelector('#device-settings-status').textContent)")
    assert dashboard.labels == {"aa00000000000002": "Updated peer"}
    assert page.locator("#data-table tbody").inner_text().count("Updated peer") == 1
    assert page.locator("#device-label").input_value() == "Updated peer"
    dashboard.view("operations")
    page.locator("#btn-jobs").click()
    page.wait_for_function("() => document.querySelectorAll('.workspace-jobs-table tbody tr').length === 2")
    page.locator(".workspace-jobs-table tbody tr").first.get_by_role("button", name="Cancel").click()
    page.wait_for_function("() => document.querySelectorAll('.workspace-jobs-table tbody tr').length === 1")
    assert dashboard.deleted == ["fixture-job"]
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#btn-cancel-all-jobs").click()
    page.wait_for_function("() => document.querySelector('#workspace-jobs-content').textContent"
                          ".includes('No pending jobs.')")
    assert dashboard.deleted == ["fixture-job", "all"]
    page.evaluate("window.__holdJobs = true")
    page.locator("#btn-refresh-jobs").click()
    page.wait_for_function("() => window.__jobsBodyWaiting === true")
    dashboard.view("table")
    jobs_content = page.locator("#workspace-jobs-content").text_content()
    page.evaluate("() => { window.__holdJobs = false; window.__releaseJobs(); }")
    page.wait_for_function("() => window.__jobsBodyReleased === true")
    page.clock.install()
    before = len([request for request in dashboard.requests if request[0] == "/api/jobs"])
    page.clock.run_for(31000)
    assert len([request for request in dashboard.requests if request[0] == "/api/jobs"]) == before
    assert page.locator("#workspace-jobs-content").text_content() == jobs_content
