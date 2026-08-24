# -*- coding: utf-8 -*-
# Copyright (c) Graphiant, Inc. | GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt)
"""Unit tests for graphiant_public_vif module (mocked Ansible + connection)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ansible_collections.graphiant.naas.plugins.modules import graphiant_public_vif


def _base_params() -> dict:
    return {
        "host": "https://api.example.com",
        "username": "u",
        "password": "p",
        "access_token": None,
        "operation": "create_services",
        "state": "present",
        "config_file": "sample_public_vif_services.yaml",
        "detailed_logs": False,
    }


def test_execute_with_logging_wraps_dict_result_with_changed_key() -> None:
    module = MagicMock()
    module.params = {"detailed_logs": False}

    out = graphiant_public_vif.execute_with_logging(
        module,
        lambda: {"changed": True, "created": ["s1"], "skipped": []},
        success_msg="ok",
    )

    assert out["changed"] is True
    assert out["result_msg"] == "ok"
    assert out["details"] == {"changed": True, "created": ["s1"], "skipped": []}


def test_execute_with_logging_non_dict_result_uses_default_success() -> None:
    module = MagicMock()
    module.params = {"detailed_logs": False}

    out = graphiant_public_vif.execute_with_logging(module, lambda: None, success_msg="ok")

    assert out["changed"] is True
    assert out["result_msg"] == "ok"


@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif.get_graphiant_connection")
@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif.AnsibleModule")
def test_main_create_services_calls_create_services(mock_ansible_module, mock_get_connection) -> None:
    mod = MagicMock()
    mod.check_mode = False
    mod._diff = False
    mod.params = _base_params()
    mock_ansible_module.return_value = mod

    public_vif = MagicMock()
    public_vif.create_services.return_value = {
        "changed": True,
        "created": ["pvif-service-1"],
        "skipped": [],
    }
    gc = MagicMock()
    gc.public_vif = public_vif
    mock_get_connection.return_value = MagicMock(graphiant_config=gc)

    graphiant_public_vif.main()

    public_vif.create_services.assert_called_once()
    args, kwargs = public_vif.create_services.call_args
    assert args[0] == "sample_public_vif_services.yaml"
    assert kwargs["diff_mode"] is False
    mod.exit_json.assert_called_once()
    exit_kwargs = mod.exit_json.call_args.kwargs
    assert exit_kwargs["changed"] is True
    assert exit_kwargs["operation"] == "create_services"


@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif.get_graphiant_connection")
@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif.AnsibleModule")
def test_main_update_services_calls_update_services(mock_ansible_module, mock_get_connection) -> None:
    mod = MagicMock()
    mod.check_mode = False
    p = _base_params()
    p["operation"] = "update_services"
    mod.params = p
    mock_ansible_module.return_value = mod

    public_vif = MagicMock()
    public_vif.update_services.return_value = {
        "changed": True,
        "updated": ["pvif-service-1"],
        "skipped": [],
    }
    gc = MagicMock()
    gc.public_vif = public_vif
    mock_get_connection.return_value = MagicMock(graphiant_config=gc)

    graphiant_public_vif.main()

    public_vif.update_services.assert_called_once_with(
        "sample_public_vif_services.yaml", vault_public_vif_bgp_md5_passwords={}
    )
    mod.exit_json.assert_called_once()
    assert mod.exit_json.call_args.kwargs["changed"] is True


@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif.get_graphiant_connection")
@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif.AnsibleModule")
def test_main_update_services_check_mode_uses_check_mode_success_message(
    mock_ansible_module, mock_get_connection
) -> None:
    mod = MagicMock()
    mod.check_mode = True
    p = _base_params()
    p["operation"] = "update_services"
    mod.params = p
    mock_ansible_module.return_value = mod

    public_vif = MagicMock()
    public_vif.update_services.return_value = {
        "changed": True,
        "updated": ["pvif-service-1"],
        "skipped": [],
    }
    gc = MagicMock()
    gc.public_vif = public_vif
    mock_get_connection.return_value = MagicMock(graphiant_config=gc)

    graphiant_public_vif.main()

    public_vif.update_services.assert_called_once_with(
        "sample_public_vif_services.yaml", vault_public_vif_bgp_md5_passwords={}
    )
    assert "Check mode" in mod.exit_json.call_args.kwargs["msg"]


@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif.get_graphiant_connection")
@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif.AnsibleModule")
def test_main_delete_services_calls_delete_services(mock_ansible_module, mock_get_connection) -> None:
    mod = MagicMock()
    mod.check_mode = False
    p = _base_params()
    p["operation"] = None
    p["state"] = "absent"
    mod.params = p
    mock_ansible_module.return_value = mod

    public_vif = MagicMock()
    public_vif.delete_services.return_value = {
        "changed": True,
        "deleted": ["pvif-service-1"],
        "skipped": [],
    }
    gc = MagicMock()
    gc.public_vif = public_vif
    mock_get_connection.return_value = MagicMock(graphiant_config=gc)

    graphiant_public_vif.main()

    public_vif.delete_services.assert_called_once_with("sample_public_vif_services.yaml")
    mod.exit_json.assert_called_once()
    assert mod.exit_json.call_args.kwargs["operation"] == "delete_services"


@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif.get_graphiant_connection")
@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif.AnsibleModule")
def test_main_missing_config_file_fails_json(mock_ansible_module, mock_get_connection) -> None:
    mod = MagicMock()
    mod.check_mode = False
    p = _base_params()
    p["config_file"] = None
    mod.params = p
    mock_ansible_module.return_value = mod
    mock_get_connection.return_value = MagicMock(graphiant_config=MagicMock())

    graphiant_public_vif.main()

    mod.fail_json.assert_called_once()
    assert "config_file parameter is required" in mod.fail_json.call_args.kwargs["msg"]


@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif.get_graphiant_connection")
@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif.AnsibleModule")
def test_main_diff_mode_sets_diff_key(mock_ansible_module, mock_get_connection) -> None:
    mod = MagicMock()
    mod.check_mode = False
    mod._diff = True
    mod.params = _base_params()
    mock_ansible_module.return_value = mod

    public_vif = MagicMock()
    public_vif.create_services.return_value = {
        "changed": True,
        "created": ["pvif-service-1"],
        "skipped": [],
        "diff_plan": [
            {
                "device": "pvif-service-1",
                "branch": "create",
                "before": {},
                "after": {"lanSegmentId": 1},
            }
        ],
    }
    gc = MagicMock()
    gc.public_vif = public_vif
    mock_get_connection.return_value = MagicMock(graphiant_config=gc)

    graphiant_public_vif.main()

    kwargs = mod.exit_json.call_args.kwargs
    assert "diff" in kwargs
    assert "pvif-service-1" in kwargs["diff"]["before"]
    assert "pvif-service-1" in kwargs["diff"]["after"]


@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif.get_graphiant_connection")
@patch("ansible_collections.graphiant.naas.plugins.modules.graphiant_public_vif.AnsibleModule")
def test_main_exception_calls_fail_json(mock_ansible_module, mock_get_connection) -> None:
    mod = MagicMock()
    mod.check_mode = False
    mod.params = _base_params()
    mock_ansible_module.return_value = mod

    public_vif = MagicMock()
    public_vif.create_services.side_effect = RuntimeError("LAN segment 'lan-x' not found")
    gc = MagicMock()
    gc.public_vif = public_vif
    mock_get_connection.return_value = MagicMock(graphiant_config=gc)

    graphiant_public_vif.main()

    mod.fail_json.assert_called_once()
    assert mod.fail_json.call_args.kwargs["operation"] == "create_services"
