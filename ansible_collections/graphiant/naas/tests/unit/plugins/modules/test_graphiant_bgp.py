# -*- coding: utf-8 -*-
# Copyright (c) Graphiant, Inc. | GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt)
"""Unit tests for graphiant_bgp module (mocked Ansible + connection).

Covers the module-layer wiring for idempotency and diff support:
no-change messaging, exit payload device lists, and the ``--diff`` key.
The manager's comparison logic is tested separately in test_bgp_manager.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ansible_collections.graphiant.naas.plugins.modules import graphiant_bgp


def _base_params() -> dict:
    return {
        "host": "https://api.example.com",
        "username": "u",
        "password": "p",
        "access_token": None,
        "bgp_config_file": "sample_bgp_peering.yaml",
        "operation": "configure",
        "state": "present",
        "detailed_logs": False,
    }


def test_execute_with_logging_no_change_adds_skipped_count_to_message() -> None:
    module = MagicMock()
    module.params = {"detailed_logs": False}
    out = graphiant_bgp.execute_with_logging(
        module,
        lambda: {
            "changed": False,
            "configured_devices": [],
            "skipped_devices": ["d1", "d2"],
        },
    )
    assert out["changed"] is False
    assert "skipped" in out["result_msg"]
    assert out["skipped_devices"] == ["d1", "d2"]


def test_execute_with_logging_changed_uses_success_msg() -> None:
    module = MagicMock()
    module.params = {"detailed_logs": False}
    out = graphiant_bgp.execute_with_logging(
        module,
        lambda: {"changed": True, "configured_devices": ["edge-1"], "skipped_devices": []},
        success_msg="done",
    )
    assert out["changed"] is True
    assert out["result_msg"] == "done"
    assert out["configured_devices"] == ["edge-1"]


@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_bgp.get_graphiant_connection")
@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_bgp.AnsibleModule")
def test_main_configure_exit_payload(mock_ansible_module, mock_get_connection) -> None:
    mod = MagicMock()
    mod.check_mode = False
    mod._diff = False
    mod.params = _base_params()
    mock_ansible_module.return_value = mod

    bgp = MagicMock()
    bgp.configure.return_value = {
        "changed": True,
        "configured_devices": ["edge-1-sdktest"],
        "skipped_devices": ["edge-2-sdktest"],
        "diff_plan": [],
    }
    gc = MagicMock()
    gc.bgp = bgp
    mock_get_connection.return_value = MagicMock(graphiant_config=gc)

    graphiant_bgp.main()

    bgp.configure.assert_called_once_with("sample_bgp_peering.yaml", {})
    mod.exit_json.assert_called_once()
    kwargs = mod.exit_json.call_args[1]
    assert kwargs["changed"] is True
    assert kwargs["operation"] == "configure"
    assert kwargs["configured_devices"] == ["edge-1-sdktest"]
    assert kwargs["skipped_devices"] == ["edge-2-sdktest"]
    assert "details" in kwargs


@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_bgp.get_graphiant_connection")
@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_bgp.AnsibleModule")
def test_main_no_change_reports_unchanged(mock_ansible_module, mock_get_connection) -> None:
    mod = MagicMock()
    mod.check_mode = False
    mod._diff = False
    mod.params = _base_params()
    mock_ansible_module.return_value = mod

    bgp = MagicMock()
    bgp.configure.return_value = {
        "changed": False,
        "configured_devices": [],
        "skipped_devices": ["edge-1-sdktest"],
        "diff_plan": [],
    }
    gc = MagicMock()
    gc.bgp = bgp
    mock_get_connection.return_value = MagicMock(graphiant_config=gc)

    graphiant_bgp.main()

    kwargs = mod.exit_json.call_args[1]
    assert kwargs["changed"] is False
    assert kwargs["skipped_devices"] == ["edge-1-sdktest"]


@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_bgp.get_graphiant_connection")
@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_bgp.AnsibleModule")
def test_main_deconfigure_via_state(mock_ansible_module, mock_get_connection) -> None:
    mod = MagicMock()
    mod.check_mode = False
    mod._diff = False
    p = _base_params()
    p["operation"] = None
    p["state"] = "absent"
    mod.params = p
    mock_ansible_module.return_value = mod

    bgp = MagicMock()
    bgp.deconfigure.return_value = {
        "changed": True,
        "configured_devices": ["edge-1-sdktest"],
        "skipped_devices": [],
        "diff_plan": [],
    }
    gc = MagicMock()
    gc.bgp = bgp
    mock_get_connection.return_value = MagicMock(graphiant_config=gc)

    graphiant_bgp.main()

    bgp.deconfigure.assert_called_once_with("sample_bgp_peering.yaml")
    kwargs = mod.exit_json.call_args[1]
    assert kwargs["operation"] == "deconfigure"


@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_bgp.get_graphiant_connection")
@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_bgp.AnsibleModule")
def test_main_detach_policies(mock_ansible_module, mock_get_connection) -> None:
    mod = MagicMock()
    mod.check_mode = False
    mod._diff = False
    p = _base_params()
    p["operation"] = "detach_policies"
    mod.params = p
    mock_ansible_module.return_value = mod

    bgp = MagicMock()
    bgp.detach_policies.return_value = {
        "changed": False,
        "configured_devices": [],
        "skipped_devices": ["edge-1-sdktest"],
        "diff_plan": [],
    }
    gc = MagicMock()
    gc.bgp = bgp
    mock_get_connection.return_value = MagicMock(graphiant_config=gc)

    graphiant_bgp.main()

    bgp.detach_policies.assert_called_once_with("sample_bgp_peering.yaml")
    kwargs = mod.exit_json.call_args[1]
    assert kwargs["operation"] == "detach_policies"


@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_bgp.get_graphiant_connection")
@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_bgp.AnsibleModule")
def test_main_diff_mode_sets_diff_key(mock_ansible_module, mock_get_connection) -> None:
    mod = MagicMock()
    mod.check_mode = False
    mod._diff = True
    mod.params = _base_params()
    mock_ansible_module.return_value = mod

    bgp = MagicMock()
    bgp.configure.return_value = {
        "changed": True,
        "configured_devices": ["edge-1-sdktest"],
        "skipped_devices": [],
        "diff_plan": [
            {
                "device": "edge-1-sdktest",
                "branch": "edge.segments",
                "before": {"segments": {"lan-1": {"bgpNeighbors": {}}}},
                "after": {
                    "segments": {"lan-1": {"bgpNeighbors": {"10.1.1.1": {"peerAsn": 65001}}}}
                },
            }
        ],
    }
    gc = MagicMock()
    gc.bgp = bgp
    mock_get_connection.return_value = MagicMock(graphiant_config=gc)

    graphiant_bgp.main()

    kwargs = mod.exit_json.call_args[1]
    assert "diff" in kwargs
    assert "edge-1-sdktest" in kwargs["diff"]["before"]
    assert "edge-1-sdktest" in kwargs["diff"]["after"]


@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_bgp.get_graphiant_connection")
@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_bgp.AnsibleModule")
def test_main_no_diff_key_when_diff_mode_off(mock_ansible_module, mock_get_connection) -> None:
    mod = MagicMock()
    mod.check_mode = False
    mod._diff = False
    mod.params = _base_params()
    mock_ansible_module.return_value = mod

    bgp = MagicMock()
    bgp.configure.return_value = {
        "changed": True,
        "configured_devices": ["edge-1-sdktest"],
        "skipped_devices": [],
        "diff_plan": [
            {"device": "edge-1-sdktest", "branch": "edge.segments", "before": {}, "after": {"x": 1}}
        ],
    }
    gc = MagicMock()
    gc.bgp = bgp
    mock_get_connection.return_value = MagicMock(graphiant_config=gc)

    graphiant_bgp.main()

    kwargs = mod.exit_json.call_args[1]
    assert "diff" not in kwargs
