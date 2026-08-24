# -*- coding: utf-8 -*-
# Copyright (c) Graphiant, Inc. | GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt)
"""Unit tests for public_vif_manager helpers (no live API)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ansible_collections.graphiant.naas.plugins.module_utils.libs.public_vif_manager import (
    PublicVifManager,
)
from ansible_collections.graphiant.naas.plugins.module_utils.libs.exceptions import (
    ConfigurationError,
    DeviceNotFoundError,
    SiteNotFoundError,
)


def _make_manager() -> PublicVifManager:
    config_utils = MagicMock()
    config_utils.gsdk = MagicMock()
    config_utils.template = MagicMock()
    return PublicVifManager(config_utils)


def _allow_gateway(mgr: PublicVifManager, device_id: int = 200) -> None:
    """Mock get_public_vif_gateways to allow *device_id* (see _validate_gateway_devices)."""
    mgr.gsdk.get_public_vif_gateways.return_value = [SimpleNamespace(device_id=device_id, hostname=f"gw-{device_id}")]


def _allow_lan_segment(mgr: PublicVifManager, lan_segment_id: int = 100) -> None:
    """Mock get_lan_segments_for_gateways to allow *lan_segment_id* (see _validate_lan_segment_for_gateways)."""
    mgr.gsdk.get_lan_segments_for_gateways.return_value = [
        SimpleNamespace(id=lan_segment_id, name=f"lan-{lan_segment_id}")
    ]


def _valid_service_config() -> dict:
    return {
        "serviceName": "pvif-service-1",
        "lanSegment": "lan-1",
        "region": "us-west-1",
        "storageProvider": "AWS",
        "consumerLanSegments": {"100": {"consumerPrefixes": ["10.10.1.0/24"]}},
        "gatewayBgpNeighbors": {"200": {"peerAsn": 65001, "remoteAddress": "192.168.1.1"}},
        # natPrefixStrategy shares gatewayBgpNeighbors' key space ("200"), NOT
        # consumerLanSegments' ("100") — confirmed via a live POST/GET capture. Flat
        # {device: prefix} — always sent to the API as the 'centralized' strategy.
        "natPrefixStrategy": {"200": "100.64.0.1"},
    }


def test_service_name_prefers_service_name_key() -> None:
    assert PublicVifManager._service_name({"serviceName": "svc1", "name": "legacy"}) == "svc1"  # noqa: SLF001


def test_service_name_falls_back_to_legacy_name_key() -> None:
    assert PublicVifManager._service_name({"name": "svc1"}) == "svc1"  # noqa: SLF001 pylint: disable=protected-access


def test_service_name_raises_when_missing() -> None:
    with pytest.raises(ConfigurationError, match="'serviceName' field"):
        PublicVifManager._service_name({})  # pylint: disable=protected-access


def test_validate_cidr_prefixes_accepts_network_address() -> None:
    mgr = _make_manager()
    mgr._validate_cidr_prefixes(["10.1.1.0/24"], "svc1", "coveringPrefixes")  # pylint: disable=protected-access


def test_validate_cidr_prefixes_rejects_non_network_address() -> None:
    mgr = _make_manager()
    with pytest.raises(ConfigurationError, match="invalid coveringPrefixes prefix"):
        mgr._validate_cidr_prefixes(["10.1.1.5/24"], "svc1", "coveringPrefixes")  # pylint: disable=protected-access


def test_resolve_device_key_passes_through_numeric_string() -> None:
    mgr = _make_manager()
    assert (
        mgr._resolve_device_key("30000057493", "svc1", "gatewayBgpNeighbors") == "30000057493"
    )  # noqa: E501 pylint: disable=protected-access
    mgr.gsdk.get_device_id.assert_not_called()


def test_resolve_device_key_passes_through_numeric_int() -> None:
    mgr = _make_manager()
    assert (
        mgr._resolve_device_key(30000057493, "svc1", "gatewayBgpNeighbors") == "30000057493"
    )  # pylint: disable=protected-access
    mgr.gsdk.get_device_id.assert_not_called()


def test_resolve_device_key_resolves_device_name() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_device_id.return_value = 30000057493
    resolved = mgr._resolve_device_key(
        "edge-1-sdktest", "svc1", "gatewayBgpNeighbors"
    )  # pylint: disable=protected-access
    assert resolved == "30000057493"
    mgr.gsdk.get_device_id.assert_called_once_with("edge-1-sdktest")


def test_resolve_device_key_raises_device_not_found_with_context() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_device_id.return_value = None
    with pytest.raises(DeviceNotFoundError, match="gatewayBgpNeighbors.*not found"):
        mgr._resolve_device_key("missing-device", "svc1", "gatewayBgpNeighbors")  # pylint: disable=protected-access


def test_resolve_device_keyed_dict_resolves_all_keys() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_device_id.side_effect = {"edge-1": 100, "edge-2": 200}.get
    resolved = mgr._resolve_device_keyed_dict(  # pylint: disable=protected-access
        {"edge-1": {"peerAsn": 1}, "300": {"peerAsn": 2}, "edge-2": {"peerAsn": 3}}, "svc1", "gatewayBgpNeighbors"
    )
    assert resolved == {"100": {"peerAsn": 1}, "300": {"peerAsn": 2}, "200": {"peerAsn": 3}}


def test_build_nat_prefix_strategy_resolves_keys_and_wraps_centralized() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_device_id.return_value = 200
    resolved = mgr._build_nat_prefix_strategy(  # pylint: disable=protected-access
        {"edge-1-sdktest": "100.64.0.1"}, "svc1"
    )
    assert resolved == {"centralized": {"consumerPrefix": {"200": "100.64.0.1"}}}


def test_build_nat_prefix_strategy_passes_through_numeric_keys() -> None:
    mgr = _make_manager()
    resolved = mgr._build_nat_prefix_strategy({"200": "100.64.0.1"}, "svc1")  # pylint: disable=protected-access
    assert resolved == {"centralized": {"consumerPrefix": {"200": "100.64.0.1"}}}
    mgr.gsdk.get_device_id.assert_not_called()


def test_apply_static_bgp_neighbor_fields_forces_enabled_and_bfd() -> None:
    mgr = _make_manager()
    resolved = mgr._apply_static_bgp_neighbor_fields(  # pylint: disable=protected-access
        {"peerAsn": 65001, "remoteAddress": "192.168.1.1"}
    )
    assert resolved == {
        "peerAsn": 65001,
        "remoteAddress": "192.168.1.1",
        "enabled": True,
        "bfd": {"bfd": {"enabled": False}},
    }


def test_apply_static_bgp_neighbor_fields_overrides_user_supplied_values() -> None:
    # 'enabled'/'bfd' have no UI toggle and BFD isn't enabled yet — any user-supplied value
    # (even a contradicting one) must be silently overridden, not merged or rejected.
    mgr = _make_manager()
    resolved = mgr._apply_static_bgp_neighbor_fields(  # pylint: disable=protected-access
        {"peerAsn": 65001, "enabled": False, "bfd": {"bfd": {"enabled": True}}}
    )
    assert resolved["enabled"] is True
    assert resolved["bfd"] == {"bfd": {"enabled": False}}


# _inject_bgp_md5_vault -- YAML non-null 'md5Password' wins; else vault (service -> device)
# fills it in when both names are given; otherwise 'md5Password' is left as given (unset,
# or an explicit null).


_VAULT_MD5 = {"svc1": {"edge-1": "vaultsecret"}}


@pytest.mark.parametrize(
    "extra,device_key,vault,expected_md5",
    [
        ({"md5Password": {"md5Password": "yamlsecret"}}, "edge-1", _VAULT_MD5, {"md5Password": "yamlsecret"}),
        ({"md5Password": "yamlsecret"}, "edge-1", _VAULT_MD5, {"md5Password": "yamlsecret"}),  # plain string form
        ({"md5Password": None}, "edge-1", _VAULT_MD5, {"md5Password": "vaultsecret"}),  # vault fills null
        ({}, "edge-1", _VAULT_MD5, {"md5Password": "vaultsecret"}),  # vault fills absent key
        ({}, "edge-9", _VAULT_MD5, None),  # no vault entry for this device
        ({}, "edge-1", {}, None),  # empty vault dict
        ({"md5Password": None}, "edge-9", _VAULT_MD5, None),  # explicit null preserved, no vault match
    ],
)
def test_inject_bgp_md5_vault_precedence(extra, device_key, vault, expected_md5) -> None:
    mgr = _make_manager()
    injected = mgr._inject_bgp_md5_vault(  # pylint: disable=protected-access
        {device_key: {"peerAsn": 65001, **extra}}, "svc1", vault
    )
    expected = {"peerAsn": 65001}
    if expected_md5 is not None:
        expected["md5Password"] = expected_md5
    elif "md5Password" in extra:
        expected["md5Password"] = extra["md5Password"]
    assert injected[device_key] == expected


def test_inject_bgp_md5_vault_does_not_mutate_input() -> None:
    mgr = _make_manager()
    original = {"edge-1": {"peerAsn": 65001, "md5Password": None}}
    mgr._inject_bgp_md5_vault(original, "svc1", _VAULT_MD5)  # pylint: disable=protected-access
    assert original == {"edge-1": {"peerAsn": 65001, "md5Password": None}}


def test_build_gateway_bgp_neighbors_fills_md5_password_from_vault() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_device_id.return_value = 200
    resolved = mgr._build_gateway_bgp_neighbors(  # pylint: disable=protected-access
        {"edge-1": {"peerAsn": 65001, "md5Password": None}}, "svc1", _VAULT_MD5
    )
    assert resolved["200"]["md5Password"] == {"md5Password": "vaultsecret"}


def test_build_gateway_bgp_neighbors_yaml_md5_password_wins_over_vault() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_device_id.return_value = 200
    resolved = mgr._build_gateway_bgp_neighbors(  # pylint: disable=protected-access
        {"edge-1": {"peerAsn": 65001, "md5Password": "yamlsecret"}}, "svc1", _VAULT_MD5
    )
    assert resolved["200"]["md5Password"] == {"md5Password": "yamlsecret"}


def test_build_gateway_bgp_neighbors_resolves_keys_and_forces_static_fields() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_device_id.return_value = 200
    resolved = mgr._build_gateway_bgp_neighbors(  # pylint: disable=protected-access
        {"edge-1-sdktest": {"peerAsn": 65001}}, "svc1"
    )
    assert resolved == {
        "200": {"peerAsn": 65001, "enabled": True, "bfd": {"bfd": {"enabled": False}}},
    }


def test_set_nested_creates_intermediate_dicts() -> None:
    target: dict = {}
    PublicVifManager._set_nested(target, ("a", "b", "c"), 1)  # pylint: disable=protected-access
    assert target == {"a": {"b": {"c": 1}}}


def test_set_nested_reuses_existing_intermediate_dict() -> None:
    target = {"a": {"existing": True}}
    PublicVifManager._set_nested(target, ("a", "b"), 1)  # pylint: disable=protected-access
    assert target == {"a": {"existing": True, "b": 1}}


def test_set_nested_overwrites_non_dict_intermediate() -> None:
    target = {"a": "not-a-dict"}
    PublicVifManager._set_nested(target, ("a", "b"), 1)  # pylint: disable=protected-access
    assert target == {"a": {"b": 1}}


def test_expand_bgp_neighbor_expands_all_shorthand_fields() -> None:
    mgr = _make_manager()
    expanded = mgr._expand_bgp_neighbor(  # pylint: disable=protected-access
        {
            "peerAsn": 65001,
            "remoteAddress": "192.168.1.1",
            "localInterface": "GigabitEthernet6/0/0.100",
            "holdTimerValue": 90,
            "keepaliveTimerValue": 30,
            "multiHop": 1,
            "maxPrefixValue": 1000,
            "allowAsIn": 1,
        }
    )
    assert expanded == {
        "peerAsn": 65001,
        "remoteAddress": "192.168.1.1",
        "localInterface": {"interface": "GigabitEthernet6/0/0.100"},
        "holdTimerValue": {"timer": 90},
        "keepaliveTimerValue": {"timer": 30},
        "ebgpMultihopTtl": {"multiHop": 1},
        "maxPrefixValue": {"maxPrefix": 1000},
        "allowAsIn": {"count": 1},
    }


def test_expand_bgp_neighbor_leaves_md5_password_and_unknown_fields_untouched() -> None:
    mgr = _make_manager()
    expanded = mgr._expand_bgp_neighbor(  # pylint: disable=protected-access
        {"peerAsn": 65001, "md5Password": "secretWord", "asOverride": True}
    )
    assert expanded == {"peerAsn": 65001, "md5Password": "secretWord", "asOverride": True}


def test_expand_bgp_neighbor_expands_address_families_with_policies() -> None:
    mgr = _make_manager()
    expanded = mgr._expand_bgp_neighbor(  # pylint: disable=protected-access
        {"addressFamilies": {"ipv4": {"inboundPolicy": "Set_Pref_Community_120", "outboundPolicy": None}}}
    )
    assert expanded == {
        "addressFamilies": {
            "ipv4": {
                "family": {
                    "addressFamily": "ipv4",
                    "inboundPolicy": {"policy": "Set_Pref_Community_120"},
                    "outboundPolicy": {},
                }
            }
        }
    }


def test_expand_bgp_neighbor_address_families_without_policies_defaults_to_empty() -> None:
    mgr = _make_manager()
    expanded = mgr._expand_bgp_neighbor({"addressFamilies": {"ipv6": {}}})  # pylint: disable=protected-access
    assert expanded == {
        "addressFamilies": {"ipv6": {"family": {"addressFamily": "ipv6", "inboundPolicy": {}, "outboundPolicy": {}}}}
    }


def test_expand_bgp_neighbor_no_shorthand_fields_returns_copy_unchanged() -> None:
    mgr = _make_manager()
    original = {"peerAsn": 65001, "remoteAddress": "192.168.1.1"}
    expanded = mgr._expand_bgp_neighbor(original)  # pylint: disable=protected-access
    assert expanded == original
    assert expanded is not original


def test_build_gateway_bgp_neighbors_expands_shorthand_fields_end_to_end() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_device_id.return_value = 200
    resolved = mgr._build_gateway_bgp_neighbors(  # pylint: disable=protected-access
        {"edge-1-sdktest": {"peerAsn": 65001, "holdTimerValue": 90, "multiHop": 1}}, "svc1"
    )
    assert resolved == {
        "200": {
            "peerAsn": 65001,
            "holdTimerValue": {"timer": 90},
            "ebgpMultihopTtl": {"multiHop": 1},
            "enabled": True,
            "bfd": {"bfd": {"enabled": False}},
        }
    }


def _device_info(interfaces: list) -> SimpleNamespace:
    """Build a fake get_device_info() response with the given interface objects."""
    return SimpleNamespace(device=SimpleNamespace(interfaces=interfaces))


def test_known_device_interface_names_builds_parent_and_subinterface_names() -> None:
    device_info = _device_info(
        [
            SimpleNamespace(
                name="GigabitEthernet6/0/0",
                subinterfaces=[SimpleNamespace(vlan=100), SimpleNamespace(vlan=200)],
            ),
            SimpleNamespace(name="GigabitEthernet7/0/0", subinterfaces=[]),
        ]
    )
    names = PublicVifManager._known_device_interface_names(device_info)  # pylint: disable=protected-access
    assert names == [
        "GigabitEthernet6/0/0",
        "GigabitEthernet6/0/0.100",
        "GigabitEthernet6/0/0.200",
        "GigabitEthernet7/0/0",
    ]


def test_known_device_interface_names_handles_missing_device() -> None:
    assert PublicVifManager._known_device_interface_names(None) == []  # pylint: disable=protected-access
    assert PublicVifManager._known_device_interface_names(SimpleNamespace()) == []  # pylint: disable=protected-access


def test_validate_gateway_local_interface_passes_when_interface_exists() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_device_info.return_value = _device_info(
        [SimpleNamespace(name="GigabitEthernet6/0/0", subinterfaces=[SimpleNamespace(vlan=100)])]
    )
    mgr._validate_gateway_local_interface(  # pylint: disable=protected-access
        "200", {"localInterface": {"interface": "GigabitEthernet6/0/0.100"}}, "svc1"
    )
    mgr.gsdk.get_device_info.assert_called_once_with(200)


def test_validate_gateway_local_interface_raises_when_interface_missing() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_device_info.return_value = _device_info(
        [SimpleNamespace(name="GigabitEthernet6/0/0", subinterfaces=[])]
    )
    with pytest.raises(ConfigurationError, match="localInterface 'GigabitEthernet6/0/0.100' which does not exist"):
        mgr._validate_gateway_local_interface(  # pylint: disable=protected-access
            "200", {"localInterface": {"interface": "GigabitEthernet6/0/0.100"}}, "svc1"
        )


def test_validate_gateway_local_interface_raises_when_device_has_no_interfaces() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_device_info.return_value = None
    with pytest.raises(ConfigurationError, match="\\(none found on this device\\)"):
        mgr._validate_gateway_local_interface(  # pylint: disable=protected-access
            "200", {"localInterface": {"interface": "GigabitEthernet6/0/0.100"}}, "svc1"
        )


def test_validate_gateway_local_interface_skips_when_not_given() -> None:
    mgr = _make_manager()
    mgr._validate_gateway_local_interface("200", {"peerAsn": 65001}, "svc1")  # pylint: disable=protected-access
    mgr.gsdk.get_device_info.assert_not_called()


def test_build_gateway_bgp_neighbors_raises_when_local_interface_missing() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_device_id.return_value = 200
    mgr.gsdk.get_device_info.return_value = _device_info(
        [SimpleNamespace(name="GigabitEthernet7/0/0", subinterfaces=[])]
    )
    with pytest.raises(ConfigurationError, match="localInterface 'GigabitEthernet6/0/0.100' which does not exist"):
        mgr._build_gateway_bgp_neighbors(  # pylint: disable=protected-access
            {"edge-1-sdktest": {"peerAsn": 65001, "localInterface": "GigabitEthernet6/0/0.100"}}, "svc1"
        )


def test_validate_gateway_devices_passes_when_device_present() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_public_vif_gateways.return_value = [
        SimpleNamespace(device_id=200, hostname="gw-1-bohr-200"),
        SimpleNamespace(device_id=300, hostname="gw-2-bohr-300"),
    ]
    mgr._validate_gateway_devices(6, "AWS", {"200": {}}, "svc1")  # pylint: disable=protected-access
    mgr.gsdk.get_public_vif_gateways.assert_called_once_with(6, "AWS")


def test_validate_gateway_devices_raises_when_device_missing() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_public_vif_gateways.return_value = [SimpleNamespace(device_id=300, hostname="gw-2-bohr-300")]
    with pytest.raises(ConfigurationError, match="gatewayBgpNeighbors device ID\\(s\\) 200"):
        mgr._validate_gateway_devices(6, "AWS", {"200": {}}, "svc1")  # pylint: disable=protected-access


def test_validate_gateway_devices_error_lists_available_gateways() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_public_vif_gateways.return_value = [SimpleNamespace(device_id=300, hostname="gw-2-bohr-300")]
    with pytest.raises(ConfigurationError, match="gw-2-bohr-300 \\(300\\)"):
        mgr._validate_gateway_devices(6, "AWS", {"200": {}}, "svc1")  # pylint: disable=protected-access


def test_validate_gateway_devices_raises_with_no_gateways_available() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_public_vif_gateways.return_value = []
    with pytest.raises(ConfigurationError, match="Available gateways: none"):
        mgr._validate_gateway_devices(6, "AWS", {"200": {}}, "svc1")  # pylint: disable=protected-access


def test_build_service_payload_raises_when_gateway_not_provisioned_for_region() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_lan_segment_id.return_value = 100
    mgr.gsdk.get_region_id_by_name.return_value = 12
    mgr.gsdk.get_public_vif_gateways.return_value = [SimpleNamespace(device_id=999, hostname="gw-other")]

    with pytest.raises(ConfigurationError, match="gatewayBgpNeighbors device ID\\(s\\) 200"):
        mgr._build_service_payload(_valid_service_config(), "pvif-service-1")  # pylint: disable=protected-access

    mgr.gsdk.get_public_vif_gateways.assert_called_once_with(12, "AWS")


def test_validate_lan_segment_for_gateways_passes_when_lan_segment_present() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_lan_segments_for_gateways.return_value = [
        SimpleNamespace(id=100, name="lan-a"),
        SimpleNamespace(id=200, name="lan-b"),
    ]
    mgr._validate_lan_segment_for_gateways(100, [111, 222], "AWS", "svc1")  # pylint: disable=protected-access
    mgr.gsdk.get_lan_segments_for_gateways.assert_called_once_with([111, 222], "AWS")


def test_validate_lan_segment_for_gateways_raises_when_lan_segment_missing() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_lan_segments_for_gateways.return_value = [SimpleNamespace(id=200, name="lan-b")]
    with pytest.raises(ConfigurationError, match="lanSegment ID 100 is not configured"):
        mgr._validate_lan_segment_for_gateways(100, [111, 222], "AWS", "svc1")  # pylint: disable=protected-access


def test_validate_lan_segment_for_gateways_error_lists_available_segments() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_lan_segments_for_gateways.return_value = [SimpleNamespace(id=200, name="lan-b")]
    with pytest.raises(ConfigurationError, match="lan-b \\(200\\)"):
        mgr._validate_lan_segment_for_gateways(100, [111, 222], "AWS", "svc1")  # pylint: disable=protected-access


def test_validate_lan_segment_for_gateways_raises_with_no_segments_available() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_lan_segments_for_gateways.return_value = []
    with pytest.raises(ConfigurationError, match="Available LAN segments: none"):
        mgr._validate_lan_segment_for_gateways(100, [111], "AWS", "svc1")  # pylint: disable=protected-access


def test_build_service_payload_raises_when_lan_segment_not_on_gateway_devices() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_lan_segment_id.return_value = 100
    mgr.gsdk.get_region_id_by_name.return_value = 12
    _allow_gateway(mgr, device_id=200)
    mgr.gsdk.get_lan_segments_for_gateways.return_value = [SimpleNamespace(id=999, name="other-lan")]

    with pytest.raises(ConfigurationError, match="lanSegment ID 100 is not configured"):
        mgr._build_service_payload(_valid_service_config(), "pvif-service-1")  # pylint: disable=protected-access

    mgr.gsdk.get_lan_segments_for_gateways.assert_called_once_with([200], "AWS")


def test_build_service_payload_resolves_gateway_bgp_neighbor_device_names() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_lan_segment_id.return_value = 100
    mgr.gsdk.get_region_id_by_name.return_value = 12
    mgr.gsdk.get_device_id.return_value = 200

    config = _valid_service_config()
    config["gatewayBgpNeighbors"] = {"edge-1-sdktest": {"peerAsn": 65001, "remoteAddress": "192.168.1.1"}}
    config["natPrefixStrategy"] = {"edge-1-sdktest": "100.64.0.1"}
    _allow_gateway(mgr)
    _allow_lan_segment(mgr)

    payload = mgr._build_service_payload(config, "pvif-service-1")  # pylint: disable=protected-access

    # Resolved once for the gatewayBgpNeighbors key and once for the matching
    # natPrefixStrategy key — both name the same device.
    assert mgr.gsdk.get_device_id.call_args_list == [(("edge-1-sdktest",),), (("edge-1-sdktest",),)]
    assert payload["gatewayBgpNeighbors"] == {
        "200": {
            "peerAsn": 65001,
            "remoteAddress": "192.168.1.1",
            "enabled": True,
            "bfd": {"bfd": {"enabled": False}},
        }
    }
    assert payload["natPrefixStrategy"] == {"centralized": {"consumerPrefix": {"200": "100.64.0.1"}}}


def test_resolve_lan_segment_key_passes_through_numeric_string() -> None:
    mgr = _make_manager()
    assert mgr._resolve_lan_segment_key("547944", "svc1") == "547944"  # pylint: disable=protected-access
    mgr.gsdk.get_lan_segment_id.assert_not_called()


def test_resolve_lan_segment_key_resolves_name() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_lan_segment_id.return_value = 547944
    resolved = mgr._resolve_lan_segment_key("lan-7-test", "svc1")  # pylint: disable=protected-access
    assert resolved == "547944"
    mgr.gsdk.get_lan_segment_id.assert_called_once_with("lan-7-test")


def test_resolve_lan_segment_key_raises_when_missing() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_lan_segment_id.return_value = None
    with pytest.raises(ConfigurationError, match="LAN segment 'lan-x' not found"):
        mgr._resolve_lan_segment_key("lan-x", "svc1")  # pylint: disable=protected-access


def test_resolve_lan_segment_keyed_dict_resolves_all_keys() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_lan_segment_id.side_effect = {"lan-1": 100, "lan-2": 200}.get
    resolved = mgr._resolve_lan_segment_keyed_dict(  # pylint: disable=protected-access
        {"lan-1": {"consumerPrefixes": ["10.1.0.0/24"]}, "300": {"consumerPrefixes": ["10.2.0.0/24"]}}, "svc1"
    )
    assert resolved == {"100": {"consumerPrefixes": ["10.1.0.0/24"]}, "300": {"consumerPrefixes": ["10.2.0.0/24"]}}


def test_build_service_payload_resolves_consumer_lan_segment_names() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_region_id_by_name.return_value = 12
    mgr.gsdk.get_lan_segment_id.side_effect = {"lan-1": 100, "lan-7-test": 547944}.get
    config = _valid_service_config()
    config["lanSegment"] = "lan-1"
    config["consumerLanSegments"] = {"lan-7-test": {"consumerPrefixes": ["10.10.1.0/24"]}}
    _allow_gateway(mgr)
    _allow_lan_segment(mgr)

    payload = mgr._build_service_payload(config, "pvif-service-1")  # pylint: disable=protected-access

    assert payload["consumerLanSegments"] == {"547944": {"consumerPrefixes": ["10.10.1.0/24"]}}


def test_resolve_lan_segment_raises_when_missing() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_lan_segment_id.return_value = None
    with pytest.raises(ConfigurationError, match="LAN segment 'lan-1' not found"):
        mgr._resolve_lan_segment("lan-1", "svc1")  # pylint: disable=protected-access


def test_resolve_lan_segment_resolves_name_to_id() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_lan_segment_id.return_value = 100
    assert mgr._resolve_lan_segment("lan-1", "svc1") == 100  # pylint: disable=protected-access


def test_resolve_lan_segment_passes_through_int() -> None:
    mgr = _make_manager()
    assert mgr._resolve_lan_segment(100, "svc1") == 100  # pylint: disable=protected-access
    mgr.gsdk.get_lan_segment_id.assert_not_called()


def test_resolve_region_raises_when_missing() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_region_id_by_name.return_value = None
    with pytest.raises(ConfigurationError, match="Region 'us-west-1' not found"):
        mgr._resolve_region("us-west-1", "svc1")  # pylint: disable=protected-access


def test_resolve_region_resolves_name_to_id() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_region_id_by_name.return_value = 12
    assert mgr._resolve_region("us-west-1", "svc1") == 12  # pylint: disable=protected-access


def test_resolve_advertisement_resolves_site_names() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_site_id.side_effect = {"site-a": 11}.get
    resolved = mgr._resolve_advertisement({"sites": ["site-a"]}, "svc1")  # pylint: disable=protected-access
    assert resolved["sites"] == [11]


def test_resolve_advertisement_raises_site_not_found() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_site_id.return_value = None
    with pytest.raises(SiteNotFoundError):
        mgr._resolve_advertisement({"sites": ["missing-site"]}, "svc1")  # pylint: disable=protected-access


def test_resolve_advertisement_resolves_site_list_names() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_site_list_id.side_effect = {"list-a": 21}.get
    resolved = mgr._resolve_advertisement({"siteLists": ["list-a"]}, "svc1")  # pylint: disable=protected-access
    assert resolved["siteLists"] == [21]


def test_resolve_advertisement_passes_through_site_list_ids() -> None:
    mgr = _make_manager()
    resolved = mgr._resolve_advertisement({"siteLists": [21]}, "svc1")  # pylint: disable=protected-access
    assert resolved["siteLists"] == [21]
    mgr.gsdk.get_site_list_id.assert_not_called()


def test_resolve_advertisement_raises_site_list_not_found() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_site_list_id.return_value = None
    with pytest.raises(ConfigurationError, match="Site list 'missing-list' not found"):
        mgr._resolve_advertisement({"siteLists": ["missing-list"]}, "svc1")  # pylint: disable=protected-access


def test_build_service_payload_resolves_names_and_passes_through_dicts() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_lan_segment_id.return_value = 100
    mgr.gsdk.get_region_id_by_name.return_value = 12
    _allow_gateway(mgr)
    _allow_lan_segment(mgr)

    payload = mgr._build_service_payload(_valid_service_config(), "pvif-service-1")  # pylint: disable=protected-access

    assert payload["serviceName"] == "pvif-service-1"
    assert payload["lanSegmentId"] == 100
    assert payload["regionId"] == 12
    assert payload["storageProvider"] == "AWS"
    assert payload["consumerLanSegments"] == {"100": {"consumerPrefixes": ["10.10.1.0/24"]}}
    assert payload["gatewayBgpNeighbors"] == {
        "200": {
            "peerAsn": 65001,
            "remoteAddress": "192.168.1.1",
            "enabled": True,
            "bfd": {"bfd": {"enabled": False}},
        }
    }
    assert payload["natPrefixStrategy"] == {"centralized": {"consumerPrefix": {"200": "100.64.0.1"}}}
    assert "coveringPrefixes" not in payload
    assert payload["advertisement"] == {"sites": [], "siteLists": []}


def test_build_service_payload_defaults_advertisement_to_empty_when_absent() -> None:
    # Confirmed via a live POST/GET capture: an empty sites/siteLists pair means "advertise
    # to all symmetric sites" -- omitting 'advertisement' from the config must still push it.
    mgr = _make_manager()
    mgr.gsdk.get_lan_segment_id.return_value = 100
    mgr.gsdk.get_region_id_by_name.return_value = 12
    config = _valid_service_config()
    assert "advertisement" not in config
    _allow_gateway(mgr)
    _allow_lan_segment(mgr)

    payload = mgr._build_service_payload(config, "pvif-service-1")  # pylint: disable=protected-access

    assert payload["advertisement"] == {"sites": [], "siteLists": []}


def test_resolve_advertisement_defaults_missing_keys_to_empty_lists() -> None:
    mgr = _make_manager()
    resolved = mgr._resolve_advertisement({}, "svc1")  # pylint: disable=protected-access
    assert resolved == {"sites": [], "siteLists": []}


def test_build_service_payload_requires_lan_segment() -> None:
    mgr = _make_manager()
    config = _valid_service_config()
    del config["lanSegment"]
    with pytest.raises(ConfigurationError, match="'lanSegment' is required"):
        mgr._build_service_payload(config, "pvif-service-1")  # pylint: disable=protected-access


def test_build_service_payload_requires_consumer_lan_segments() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_lan_segment_id.return_value = 100
    mgr.gsdk.get_region_id_by_name.return_value = 12
    config = _valid_service_config()
    del config["consumerLanSegments"]
    with pytest.raises(ConfigurationError, match="'consumerLanSegments' \\(dict\\) is required"):
        mgr._build_service_payload(config, "pvif-service-1")  # pylint: disable=protected-access


def test_build_service_payload_validates_covering_prefixes() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_lan_segment_id.return_value = 100
    mgr.gsdk.get_region_id_by_name.return_value = 12
    config = _valid_service_config()
    config["coveringPrefixes"] = ["10.1.1.5/24"]
    _allow_gateway(mgr)
    _allow_lan_segment(mgr)
    with pytest.raises(ConfigurationError, match="invalid coveringPrefixes prefix"):
        mgr._build_service_payload(config, "pvif-service-1")  # pylint: disable=protected-access


def test_create_services_skips_existing_service() -> None:
    mgr = _make_manager()
    mgr.config_utils.render_config_file.return_value = {"public_vif_services": [_valid_service_config()]}
    mgr.gsdk.get_public_vif_service_by_name.return_value = SimpleNamespace(id=1, service_name="pvif-service-1")

    result = mgr.create_services("dummy.yaml")

    assert result["changed"] is False
    assert result["skipped"] == ["pvif-service-1"]
    assert result["created"] == []
    mgr.gsdk.create_public_vif_service.assert_not_called()


def test_create_services_creates_new_service() -> None:
    mgr = _make_manager()
    mgr.config_utils.render_config_file.return_value = {"public_vif_services": [_valid_service_config()]}
    mgr.gsdk.get_public_vif_service_by_name.return_value = None
    mgr.gsdk.get_lan_segment_id.return_value = 100
    mgr.gsdk.get_region_id_by_name.return_value = 12
    mgr.gsdk.create_public_vif_service.return_value = {"id": 42}
    _allow_gateway(mgr)
    _allow_lan_segment(mgr)

    result = mgr.create_services("dummy.yaml")

    assert result["changed"] is True
    assert result["created"] == ["pvif-service-1"]
    sent_payload = mgr.gsdk.create_public_vif_service.call_args[0][0]
    assert sent_payload["lanSegmentId"] == 100
    assert sent_payload["regionId"] == 12


def test_create_services_redacts_md5_password_in_diff_plan_but_not_api_call() -> None:
    # diff_plan (and by extension --diff / logs) must never show the secret in plaintext,
    # even though the real API payload sent to gsdk still carries it.
    mgr = _make_manager()
    config = _valid_service_config()
    config["gatewayBgpNeighbors"] = {"200": {"peerAsn": 65001, "md5Password": {"md5Password": "supersecret"}}}
    mgr.config_utils.render_config_file.return_value = {"public_vif_services": [config]}
    mgr.gsdk.get_public_vif_service_by_name.return_value = None
    mgr.gsdk.get_lan_segment_id.return_value = 100
    mgr.gsdk.get_region_id_by_name.return_value = 12
    mgr.gsdk.create_public_vif_service.return_value = {"id": 42}
    _allow_gateway(mgr)
    _allow_lan_segment(mgr)

    result = mgr.create_services("dummy.yaml")

    diff_after = result["diff_plan"][0]["after"]
    assert diff_after["gatewayBgpNeighbors"]["200"]["md5Password"] == "********"

    sent_payload = mgr.gsdk.create_public_vif_service.call_args[0][0]
    assert sent_payload["gatewayBgpNeighbors"]["200"]["md5Password"] == {"md5Password": "supersecret"}


def test_update_services_raises_when_service_missing() -> None:
    mgr = _make_manager()
    mgr.config_utils.render_config_file.return_value = {"public_vif_services": [_valid_service_config()]}
    mgr.gsdk.get_public_vif_service_by_name.return_value = None

    with pytest.raises(ConfigurationError, match="not found"):
        mgr.update_services("dummy.yaml")


def test_update_services_always_pushes_and_reports_changed() -> None:
    mgr = _make_manager()
    mgr.config_utils.render_config_file.return_value = {"public_vif_services": [_valid_service_config()]}
    mgr.gsdk.get_public_vif_service_by_name.return_value = SimpleNamespace(id=7, service_name="pvif-service-1")
    mgr.gsdk.get_lan_segment_id.return_value = 100
    mgr.gsdk.get_region_id_by_name.return_value = 12
    _allow_gateway(mgr)
    _allow_lan_segment(mgr)

    result = mgr.update_services("dummy.yaml")

    assert result["changed"] is True
    assert result["updated"] == ["pvif-service-1"]
    mgr.gsdk.edit_public_vif_service.assert_called_once()
    assert mgr.gsdk.edit_public_vif_service.call_args[0][0] == 7


def test_update_services_redacts_md5_password_in_diff_plan_but_not_api_call() -> None:
    mgr = _make_manager()
    config = _valid_service_config()
    config["gatewayBgpNeighbors"] = {"200": {"peerAsn": 65001, "md5Password": {"md5Password": "supersecret"}}}
    mgr.config_utils.render_config_file.return_value = {"public_vif_services": [config]}
    mgr.gsdk.get_public_vif_service_by_name.return_value = SimpleNamespace(id=7, service_name="pvif-service-1")
    mgr.gsdk.get_lan_segment_id.return_value = 100
    mgr.gsdk.get_region_id_by_name.return_value = 12
    _allow_gateway(mgr)
    _allow_lan_segment(mgr)

    result = mgr.update_services("dummy.yaml")

    diff_after = result["diff_plan"][0]["after"]
    assert diff_after["gatewayBgpNeighbors"]["200"]["md5Password"] == "********"

    sent_payload = mgr.gsdk.edit_public_vif_service.call_args[0][1]
    assert sent_payload["gatewayBgpNeighbors"]["200"]["md5Password"] == {"md5Password": "supersecret"}


def test_delete_services_skips_when_not_found() -> None:
    mgr = _make_manager()
    mgr.config_utils.render_config_file.return_value = {"public_vif_services": [{"name": "pvif-service-1"}]}
    mgr.gsdk.get_public_vif_service_by_name.return_value = None

    result = mgr.delete_services("dummy.yaml")

    assert result["changed"] is False
    assert result["skipped"] == ["pvif-service-1"]
    assert result["deleted"] == []
    mgr.gsdk.delete_public_vif_service.assert_not_called()


def test_delete_services_deletes_existing_service() -> None:
    mgr = _make_manager()
    mgr.config_utils.render_config_file.return_value = {"public_vif_services": [{"name": "pvif-service-1"}]}
    mgr.gsdk.get_public_vif_service_by_name.return_value = SimpleNamespace(id=7, service_name="pvif-service-1")

    result = mgr.delete_services("dummy.yaml")

    assert result["changed"] is True
    assert result["deleted"] == ["pvif-service-1"]
    mgr.gsdk.delete_public_vif_service.assert_called_once_with(7)


def test_get_services_summary_shapes_output() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_public_vif_services_summary.return_value = [
        SimpleNamespace(id=1, service_name="pvif-service-1", user_name="jdoe", updated_at="2026-08-14T00:00:00Z")
    ]

    result = mgr.get_services_summary()

    assert result == {
        "services": [
            {"id": 1, "serviceName": "pvif-service-1", "userName": "jdoe", "updatedAt": "2026-08-14T00:00:00Z"}
        ]
    }


def test_get_service_details_raises_when_not_found() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_public_vif_service_by_name.return_value = None

    with pytest.raises(ConfigurationError, match="not found"):
        mgr.get_service_details("pvif-service-1")


def test_get_service_details_returns_details() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_public_vif_service_by_name.return_value = SimpleNamespace(id=7, service_name="pvif-service-1")
    mgr.gsdk.get_public_vif_service_details.return_value = {"id": 7, "serviceName": "pvif-service-1"}

    result = mgr.get_service_details("pvif-service-1")

    assert result == {"id": 7, "serviceName": "pvif-service-1"}
    mgr.gsdk.get_public_vif_service_details.assert_called_once_with(7)
