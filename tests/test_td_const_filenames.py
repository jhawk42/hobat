import re
from pathlib import Path

import pytest

import td_const


EXPECTED_JSON_FILENAMES = {
    "EXTADDR_DEVICE_LABEL_MAP_FILENAME": "td-static-extaddr-device-label.json",
    "LEGACY_THREADSTATIC_EXTADDR_FILENAME": "threadstatic-extaddr.json",
    "MDNS_SCOPES_THREAD_FILENAME": "td-mdns-scopes-thread.json",
    "MDNS_SCOPES_BR_FILENAME": "td-mdns-scopes-br.json",
    "MDNS_SCOPES_HAP_FILENAME": "td-mdns-scopes-hap.json",
    "MDNS_SCOPES_MATTER_FILENAME": "td-mdns-scopes-matter.json",
    "OTBR_CLI_THREAD_NETWORK_INFO_FILENAME": "td-otbr-cli-thread-network-info.json",
    "OTBR_CLI_ROUTER_TABLE_FILENAME": "td-otbr-cli-router-table.json",
    "OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME": "td-otbr-cli-meshdiag-topology.json",
    "OTBR_CLI_MESHDIAG_ROUTER_CHILDIP6_FILENAME": "td-otbr-cli-meshdiag-router-childip6.json",
    "OTBR_CLI_MESHDIAG_ROUTER_CHILDTABLES_FILENAME": "td-otbr-cli-meshdiag-router-childtables.json",
    "OTBR_CLI_MESHDIAG_ROUTER_NEIGHBORTABLES_FILENAME": "td-otbr-cli-meshdiag-router-neighbortables.json",
    "OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME": "td-otbr-cli-networkdiag-fetch-all.json",
    "OTBR_CLI_NETWORKDIAG_MULTICAST_NETWORK_FILENAME": "td-otbr-cli-networkdiag-multicast-network.json",
    "OTBR_CLI_NETWORKDIAG_MULTICAST_NEIGHBORS_FILENAME": "td-otbr-cli-networkdiag-multicast-neighbors.json",
    "OTBR_RESTAPI_DATASET_ACTIVE_FILENAME": "td-otbr-restapi-dataset-active.json",
    "OTBR_RESTAPI_DEVICES_FILENAME": "td-otbr-restapi-devices.json",
    "OTBR_RESTAPI_DEVICES_LIST_FILENAME": "td-otbr-restapi-devices-list.json",
    "OTBR_RESTAPI_DEVICES_FETCH_FILENAME": "td-otbr-restapi-devices-fetch.json",
    "OTBR_RESTAPI_DIAGNOSTICS_FILENAME": "td-otbr-restapi-diagnostics.json",
    "OTBR_RESTAPI_DIAGNOSTICS_LIST_FILENAME": "td-otbr-restapi-diagnostics-list.json",
    "OTBR_RESTAPI_DIAGNOSTICS_FETCH_FILENAME": "td-otbr-restapi-diagnostics-fetch.json",
    "OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME": "td-otbr-restapi-diagnostics-fetch-all.json",
    "OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME": "td-otbr-restapi-diagnostics-fetch-all.outcome.json",
    "OTBR_RESTAPI_ACTIONS_LIST_FILENAME": "td-otbr-restapi-actions-list.json",
    "OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_FILENAME": "td-otbr-restapi-mesh-diagnostics-fetch.json",
    "OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME": "td-otbr-restapi-mesh-diagnostics-fetch-all.json",
    "OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME": "td-otbr-restapi-mesh-diagnostics-fetch-all.outcome.json",
    "EVE_TOPOLOGY_FILENAME": "td-eve-topology.json",
    "THREAD_TOOLS_DIAGNOSTICS_FILENAME": "diagnostics.json",
    "MERGED_TOPOLOGY_ALL_FILENAME": "td-merged-topology-all.json",
}


@pytest.mark.parametrize(("name", "value"), EXPECTED_JSON_FILENAMES.items())
def test_project_json_filename_values(name, value):
    assert getattr(td_const, name) == value


def test_dynamic_json_filename_families():
    assert dict(td_const.MDNS_SCOPE_FILENAMES) == {
        "thread": td_const.MDNS_SCOPES_THREAD_FILENAME,
        "br": td_const.MDNS_SCOPES_BR_FILENAME,
        "hap": td_const.MDNS_SCOPES_HAP_FILENAME,
        "matter": td_const.MDNS_SCOPES_MATTER_FILENAME,
    }
    with pytest.raises(TypeError):
        td_const.MDNS_SCOPE_FILENAMES["thread"] = "changed.json"
    assert td_const.OTBR_RESTAPI_DEVICE_DIAGNOSTIC_FILENAME_TEMPLATE == (
        "td-otbr-restapi-diagnostic-{device_id}.json"
    )


def test_production_modules_do_not_duplicate_project_json_filename_literals():
    src_dir = Path(__file__).parents[1] / "src"
    filenames = set(EXPECTED_JSON_FILENAMES.values())
    filenames.add(td_const.OTBR_RESTAPI_DEVICE_DIAGNOSTIC_FILENAME_TEMPLATE)
    literal_pattern = re.compile(
        rf"(?P<quote>['\"])(?:{'|'.join(re.escape(name) for name in sorted(filenames, key=len, reverse=True))})(?P=quote)"
    )

    duplicates = []
    for path in sorted(src_dir.glob("*.py")):
        if path.name == "td_const.py":
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if literal_pattern.search(line):
                duplicates.append(f"{path.relative_to(src_dir.parent)}:{line_number}")

    assert duplicates == []