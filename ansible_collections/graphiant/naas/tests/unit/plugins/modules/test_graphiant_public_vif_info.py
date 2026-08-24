# -*- coding: utf-8 -*-
# Copyright (c) Graphiant, Inc. | GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt)
"""Unit tests for graphiant_public_vif_info module (mocked Ansible + connection)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ansible_collections.graphiant.naas.plugins.modules import graphiant_public_vif_info


def _base_params() -> dict:
    return {
        "host": "https://api.example.com",
        "username": "u",
        "password": "p",
        "access_token": None,
        "query": "services_summary",
        "service_name": None,
        "detailed_logs": False,
    }


def test_execute_with_logging_wraps_plain_dict_as_result_data() -> None:
    """
    Regression: manager query methods (get_services_summary, get_service_details) return
    their payload directly, with no "result_msg" key of their own — the whole dict must be
    preserved as result_data, not dropped.
    """
    module = MagicMock()
    module.params = {"detailed_logs": False}

    out = graphiant_public_vif_info.execute_with_logging(
        module, lambda: {"services": [{"id": 1, "serviceName": "pvif-service-1"}]}, success_msg="ok"
    )

    assert out["result_msg"] == "ok"
    assert out["result_data"] == {"services": [{"id": 1, "serviceName": "pvif-service-1"}]}


def test_execute_with_logging_non_dict_result_returns_empty_result_data() -> None:
    module = MagicMock()
    module.params = {"detailed_logs": False}

    out = graphiant_public_vif_info.execute_with_logging(module, lambda: None, success_msg="ok")

    assert out["result_msg"] == "ok"
    assert out["result_data"] == {}


@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif_info.get_graphiant_connection")
@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif_info.AnsibleModule")
def test_main_services_summary_calls_get_services_summary(mock_ansible_module, mock_get_connection) -> None:
    mod = MagicMock()
    mod.check_mode = False
    mod.params = _base_params()
    mock_ansible_module.return_value = mod

    public_vif = MagicMock()
    public_vif.get_services_summary.return_value = {
        "services": [{"id": 1, "serviceName": "pvif-service-1", "userName": "jdoe"}]
    }
    gc = MagicMock()
    gc.public_vif = public_vif
    mock_get_connection.return_value = MagicMock(graphiant_config=gc)

    graphiant_public_vif_info.main()

    public_vif.get_services_summary.assert_called_once_with()
    mod.exit_json.assert_called_once()
    kwargs = mod.exit_json.call_args.kwargs
    assert kwargs["changed"] is False
    assert kwargs["query"] == "services_summary"
    assert kwargs["result_data"]["services"][0]["serviceName"] == "pvif-service-1"


@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif_info.get_graphiant_connection")
@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif_info.AnsibleModule")
def test_main_service_details_passes_service_name(mock_ansible_module, mock_get_connection) -> None:
    mod = MagicMock()
    mod.check_mode = False
    p = _base_params()
    p["query"] = "service_details"
    p["service_name"] = "pvif-service-1"
    mod.params = p
    mock_ansible_module.return_value = mod

    public_vif = MagicMock()
    public_vif.get_service_details.return_value = {"id": 1, "serviceName": "pvif-service-1"}
    gc = MagicMock()
    gc.public_vif = public_vif
    mock_get_connection.return_value = MagicMock(graphiant_config=gc)

    graphiant_public_vif_info.main()

    public_vif.get_service_details.assert_called_once_with("pvif-service-1")
    kwargs = mod.exit_json.call_args.kwargs
    assert kwargs["result_data"]["serviceName"] == "pvif-service-1"


@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif_info.get_graphiant_connection")
@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif_info.AnsibleModule")
def test_main_unsupported_query_fails_json(mock_ansible_module, mock_get_connection) -> None:
    mod = MagicMock()
    mod.check_mode = False
    p = _base_params()
    p["query"] = "not-a-real-query"
    mod.params = p
    mock_ansible_module.return_value = mod
    mock_get_connection.return_value = MagicMock(graphiant_config=MagicMock())

    graphiant_public_vif_info.main()

    mod.fail_json.assert_called_once()
    assert "Unsupported query" in mod.fail_json.call_args.kwargs["msg"]


@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif_info.get_graphiant_connection")
@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif_info.AnsibleModule")
def test_main_exception_calls_fail_json(mock_ansible_module, mock_get_connection) -> None:
    mod = MagicMock()
    mod.check_mode = False
    mod.params = _base_params()
    mock_ansible_module.return_value = mod

    public_vif = MagicMock()
    public_vif.get_services_summary.side_effect = RuntimeError("boom")
    gc = MagicMock()
    gc.public_vif = public_vif
    mock_get_connection.return_value = MagicMock(graphiant_config=gc)

    graphiant_public_vif_info.main()

    mod.fail_json.assert_called_once()
    assert "boom" in mod.fail_json.call_args.kwargs["msg"]
