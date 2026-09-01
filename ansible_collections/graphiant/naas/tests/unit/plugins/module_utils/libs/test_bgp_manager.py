# -*- coding: utf-8 -*-
# Copyright (c) Graphiant, Inc. | GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt)
"""Unit tests for BGPManager idempotency and diff support."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ansible_collections.graphiant.naas.plugins.module_utils.libs.bgp_manager import BGPManager
from ansible_collections.graphiant.naas.plugins.module_utils.libs.exceptions import ConfigurationError


def _make_manager() -> BGPManager:
    config_utils = MagicMock()
    config_utils.gsdk = MagicMock()
    config_utils.template = MagicMock()
    return BGPManager(config_utils)


def _desired_payload(config: dict, action: str = "add") -> dict:
    """Build a desired device payload via the manager's static builder (no gsdk needed)."""
    route_policies = config.get("routePolicies") or []
    return BGPManager._build_bgp_peering(  # pylint: disable=protected-access
        action=action,
        segments=config.get("segments") or [],
        route_policies=route_policies,
        global_ids={name: idx + 1 for idx, name in enumerate(route_policies)},
    )


# A GET-response neighbor that exactly matches the desired defaults for 10.1.1.1/peerAs 65001.
def _get_neighbor(**overrides) -> dict:
    base = {
        "remoteAddress": "10.1.1.1",
        "peerAsn": 65001,
        "holdTimer": 90,
        "keepaliveTimer": 30,
        "multiHop": 1,
        "sendCommunity": True,
        "asOverride": False,
        "removePrivateAs": False,
        "bfd": {"enabled": False},
        "addressFamilies": [
            {"addressFamily": "ipv4"},
            {"addressFamily": "ipv6"},
        ],
    }
    base.update(overrides)
    return base


def _device_dict(neighbors=None, aggregations=None, routing_policies=None, seg_name="lan-1") -> dict:
    return {
        "segments": [
            {
                "name": seg_name,
                "bgpNeighbors": neighbors or [],
                "bgpAggregations": aggregations or [],
            }
        ],
        "routingPolicies": routing_policies or [],
    }


_NEIGHBOR_CFG = {"remoteIpv4Address": "10.1.1.1", "peerAs": 65001}


# --- normalized helpers ------------------------------------------------------

def test_normalized_desired_matches_get_for_identical_neighbor() -> None:
    payload = _desired_payload({"segments": [{"lanSegment": "lan-1", "neighbors": [_NEIGHBOR_CFG]}]})
    desired = payload["segments"]["lan-1"]["bgpNeighbors"]["10.1.1.1"]["neighbor"]
    d_norm = BGPManager._normalized_neighbor_from_desired(desired)
    e_norm = BGPManager._normalized_neighbor_from_get(_get_neighbor())
    # Every key the desired push asserts is already present with the same value.
    assert not BGPManager._sparse_differs(d_norm, e_norm)


# --- configure idempotency --------------------------------------------------

def test_device_diff_no_change_when_neighbor_matches() -> None:
    mgr = _make_manager()
    payload = _desired_payload({"segments": [{"lanSegment": "lan-1", "neighbors": [_NEIGHBOR_CFG]}]})
    device_dict = _device_dict(neighbors=[_get_neighbor()])
    changed, _before, _after = mgr._device_diff(payload, device_dict, action="add")
    assert changed is False


def test_device_diff_change_when_peerAsn_differs() -> None:
    mgr = _make_manager()
    payload = _desired_payload({"segments": [{"lanSegment": "lan-1", "neighbors": [_NEIGHBOR_CFG]}]})
    device_dict = _device_dict(neighbors=[_get_neighbor(peerAsn=99999)])
    changed, _before, _after = mgr._device_diff(payload, device_dict, action="add")
    assert changed is True


def test_device_diff_change_when_neighbor_absent() -> None:
    mgr = _make_manager()
    payload = _desired_payload({"segments": [{"lanSegment": "lan-1", "neighbors": [_NEIGHBOR_CFG]}]})
    device_dict = _device_dict(neighbors=[])
    changed, _before, _after = mgr._device_diff(payload, device_dict, action="add")
    assert changed is True


def test_device_diff_change_when_inbound_policy_differs() -> None:
    mgr = _make_manager()
    cfg = {"remoteIpv4Address": "10.1.1.1", "peerAs": 65001, "ipv4InboundFilter": "p1"}
    payload = _desired_payload({"segments": [{"lanSegment": "lan-1", "neighbors": [cfg]}]})
    # Device currently has a different inbound policy attached.
    existing = _get_neighbor(
        addressFamilies=[{"addressFamily": "ipv4", "inboundPolicy": "other"}, {"addressFamily": "ipv6"}]
    )
    device_dict = _device_dict(neighbors=[existing])
    changed, _before, _after = mgr._device_diff(payload, device_dict, action="add")
    assert changed is True


def test_device_diff_no_change_when_inbound_policy_matches() -> None:
    mgr = _make_manager()
    cfg = {"remoteIpv4Address": "10.1.1.1", "peerAs": 65001, "ipv4InboundFilter": "p1"}
    payload = _desired_payload({"segments": [{"lanSegment": "lan-1", "neighbors": [cfg]}]})
    existing = _get_neighbor(
        addressFamilies=[{"addressFamily": "ipv4", "inboundPolicy": "p1"}, {"addressFamily": "ipv6"}]
    )
    device_dict = _device_dict(neighbors=[existing])
    changed, _before, _after = mgr._device_diff(payload, device_dict, action="add")
    assert changed is False


def test_device_diff_aggregation_match_and_mismatch() -> None:
    mgr = _make_manager()
    cfg = {
        "lanSegment": "lan-1",
        "bgpAggregations": [{"prefix": "1.1.1.0/27", "asSet": True, "summaryOnly": True}],
    }
    payload = _desired_payload({"segments": [cfg]})

    matching = _device_dict(aggregations=[{"prefix": "1.1.1.0/27", "asSet": True, "summaryOnly": True}])
    assert mgr._device_diff(payload, matching, action="add")[0] is False

    mismatch = _device_dict(aggregations=[{"prefix": "1.1.1.0/27", "asSet": False, "summaryOnly": True}])
    assert mgr._device_diff(payload, mismatch, action="add")[0] is True


def test_device_diff_change_when_route_policy_not_attached() -> None:
    mgr = _make_manager()
    payload = _desired_payload(
        {
            "routePolicies": ["demo_bgp_inbound_filter"],
            "segments": [{"lanSegment": "lan-1", "neighbors": [_NEIGHBOR_CFG]}],
        }
    )
    # Neighbor matches, but the device-level routing policy is not attached yet.
    device_dict = _device_dict(neighbors=[_get_neighbor()], routing_policies=[])
    assert mgr._device_diff(payload, device_dict, action="add")[0] is True

    device_dict_attached = _device_dict(
        neighbors=[_get_neighbor()], routing_policies=[{"name": "demo_bgp_inbound_filter"}]
    )
    assert mgr._device_diff(payload, device_dict_attached, action="add")[0] is False


# --- deconfigure idempotency ------------------------------------------------

def test_device_diff_delete_change_only_when_present() -> None:
    mgr = _make_manager()
    payload = _desired_payload(
        {"segments": [{"lanSegment": "lan-1", "neighbors": [_NEIGHBOR_CFG]}]}, action="delete"
    )
    present = _device_dict(neighbors=[_get_neighbor()])
    assert mgr._device_diff(payload, present, action="delete")[0] is True

    absent = _device_dict(neighbors=[])
    assert mgr._device_diff(payload, absent, action="delete")[0] is False


# --- per-entry state: absent on configure -----------------------------------

def test_device_diff_per_neighbor_absent_change_only_when_present() -> None:
    mgr = _make_manager()
    cfg = {
        "lanSegment": "lan-1",
        "neighbors": [{"remoteIpv4Address": "10.1.1.1", "peerAs": 65001, "state": "absent"}],
    }
    payload = _desired_payload({"segments": [cfg]}, action="add")
    # Sanity: the builder produced a deletion payload for this neighbor under configure.
    assert payload["segments"]["lan-1"]["bgpNeighbors"]["10.1.1.1"] == {"neighbor": None}

    present = _device_dict(neighbors=[_get_neighbor()])
    assert mgr._device_diff(payload, present, action="add")[0] is True

    absent = _device_dict(neighbors=[])
    assert mgr._device_diff(payload, absent, action="add")[0] is False


def test_device_diff_mixed_absent_and_present_neighbors() -> None:
    mgr = _make_manager()
    cfg = {
        "lanSegment": "lan-1",
        "neighbors": [
            {"remoteIpv4Address": "10.1.1.1", "peerAs": 65001},  # keep (already matches)
            {"remoteIpv4Address": "10.1.1.2", "peerAs": 65002, "state": "absent"},  # remove
        ],
    }
    payload = _desired_payload({"segments": [cfg]}, action="add")

    # Matching neighbor present, absent-target already gone -> no change.
    device_dict = _device_dict(neighbors=[_get_neighbor()])
    assert mgr._device_diff(payload, device_dict, action="add")[0] is False

    # Absent-target still on the device -> change needed (just to remove it).
    with_target = _device_dict(
        neighbors=[_get_neighbor(), _get_neighbor(remoteAddress="10.1.1.2", peerAsn=65002)]
    )
    assert mgr._device_diff(payload, with_target, action="add")[0] is True


# --- detach a single policy from a kept neighbor via `absent` ----------------

def test_device_diff_detach_policy_via_absent_change_only_when_attached() -> None:
    mgr = _make_manager()
    cfg = {
        "remoteIpv4Address": "10.1.1.1",
        "peerAs": 65001,
        "ipv4InboundFilter": "absent",  # detach inbound, keep the neighbor
    }
    payload = _desired_payload({"segments": [{"lanSegment": "lan-1", "neighbors": [cfg]}]}, action="add")
    # The neighbor is kept (not a deletion), only its inbound policy is nulled.
    assert payload["segments"]["lan-1"]["bgpNeighbors"]["10.1.1.1"]["neighbor"] is not None

    # Inbound policy currently attached -> detaching it is a change.
    attached = _device_dict(
        neighbors=[_get_neighbor(addressFamilies=[{"addressFamily": "ipv4", "inboundPolicy": "p1"},
                                                  {"addressFamily": "ipv6"}])]
    )
    assert mgr._device_diff(payload, attached, action="add")[0] is True

    # Inbound policy already absent -> no change.
    already = _device_dict(
        neighbors=[_get_neighbor(addressFamilies=[{"addressFamily": "ipv4"}, {"addressFamily": "ipv6"}])]
    )
    assert mgr._device_diff(payload, already, action="add")[0] is False


# --- detach_policies (detach) idempotency -----------------------------------

def test_device_diff_detach_change_only_when_policy_attached() -> None:
    mgr = _make_manager()
    cfg = {
        "remoteIpv4Address": "10.1.1.1",
        "peerAs": 65001,
        "ipv4InboundFilter": "p1",
        "ipv4OutboundFilter": "p2",
    }
    payload = _desired_payload({"segments": [{"lanSegment": "lan-1", "neighbors": [cfg]}]}, action="detach")

    attached = _device_dict(
        neighbors=[
            _get_neighbor(
                addressFamilies=[
                    {"addressFamily": "ipv4", "inboundPolicy": "p1", "outboundPolicy": "p2"},
                    {"addressFamily": "ipv6"},
                ]
            )
        ]
    )
    assert mgr._device_diff(payload, attached, action="detach")[0] is True

    already_detached = _device_dict(
        neighbors=[_get_neighbor(addressFamilies=[{"addressFamily": "ipv4"}, {"addressFamily": "ipv6"}])]
    )
    assert mgr._device_diff(payload, already_detached, action="detach")[0] is False


# --- apply() end-to-end (mocked I/O) ---------------------------------------

@patch("ansible_collections.graphiant.naas.plugins.module_utils.libs.bgp_manager.fetch_device_by_name")
def test_apply_skips_matching_device_and_pushes_changed(mock_fetch) -> None:
    mgr = _make_manager()
    mgr.gsdk.enterprise_info = {"company_name": "acme"}

    config = {
        "bgpPeering": [
            {"edge-match": {"segments": [{"lanSegment": "lan-1", "neighbors": [_NEIGHBOR_CFG]}]}},
            {"edge-diff": {"segments": [{"lanSegment": "lan-1", "neighbors": [_NEIGHBOR_CFG]}]}},
        ]
    }
    mgr.render_config_file = MagicMock(return_value=config)

    # apply() builds the payload itself via _build_device_payload (no route
    # policies here, so gsdk is not consulted).

    def _fetch(_gsdk, device_name, _enterprise):
        if device_name == "edge-match":
            return 1, _device_dict(neighbors=[_get_neighbor()])
        return 2, _device_dict(neighbors=[_get_neighbor(peerAsn=99999)])

    mock_fetch.side_effect = _fetch
    mgr.execute_concurrent_tasks = MagicMock()

    result = mgr.apply("bgp.yaml", action="add")

    assert result["changed"] is True
    assert result["skipped_devices"] == ["edge-match"]
    assert result["configured_devices"] == ["edge-diff"]
    assert len(result["diff_plan"]) == 1
    # Only the changed device is pushed.
    pushed = mgr.execute_concurrent_tasks.call_args[0][1]
    assert list(pushed.keys()) == [2]


@patch("ansible_collections.graphiant.naas.plugins.module_utils.libs.bgp_manager.fetch_device_by_name")
def test_apply_no_push_when_all_match(mock_fetch) -> None:
    mgr = _make_manager()
    mgr.gsdk.enterprise_info = {"company_name": "acme"}
    config = {"bgpPeering": [{"edge-1": {"segments": [{"lanSegment": "lan-1", "neighbors": [_NEIGHBOR_CFG]}]}}]}
    mgr.render_config_file = MagicMock(return_value=config)
    mock_fetch.return_value = (1, _device_dict(neighbors=[_get_neighbor()]))
    mgr.execute_concurrent_tasks = MagicMock()

    result = mgr.apply("bgp.yaml", action="add")

    assert result["changed"] is False
    assert result["skipped_devices"] == ["edge-1"]
    assert result["configured_devices"] == []
    mgr.execute_concurrent_tasks.assert_not_called()


# --- _build_device_payload (config entry -> edge PUT payload) ---------------

def test_build_device_payload_resolves_routePolicies() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_global_routing_policy_id.side_effect = lambda n: 42 if n == "p1" else 99
    config = {
        "routePolicies": ["p1", "p2"],
        "segments": [
            {
                "lanSegment": "lan-1",
                "neighbors": [
                    {
                        "remoteIpv4Address": "10.1.1.1",
                        "peerAs": 65001,
                        "localInterface": "GigabitEthernet1/0/0.1",
                        "ipv4InboundFilter": "p1",
                        "ipv4OutboundFilter": "p2",
                        "bfd": True,
                        "minimumInterval": 1200,
                        "localMultiplier": 4,
                    }
                ],
                "bgpAggregations": [{"prefix": "1.1.1.0/27", "asSet": True, "summaryOnly": True}],
            }
        ],
    }
    payload = mgr._build_device_payload(config, "add")

    assert payload["routePolicies"] == {
        "p1": {"policy": {"globalId": 42, "isGlobalSync": True}},
        "p2": {"policy": {"globalId": 99, "isGlobalSync": True}},
    }
    neighbor = payload["segments"]["lan-1"]["bgpNeighbors"]["10.1.1.1"]["neighbor"]
    assert neighbor["peerAsn"] == 65001
    assert neighbor["localInterface"] == {"interface": "GigabitEthernet1/0/0.1"}
    assert neighbor["bfd"]["bfd"] == {"enabled": True, "minimumInterval": 1200, "localMultiplier": 4}
    assert neighbor["addressFamilies"]["ipv4"]["family"]["inboundPolicy"] == {"policy": "p1"}
    assert neighbor["addressFamilies"]["ipv4"]["family"]["outboundPolicy"] == {"policy": "p2"}
    aggregation = payload["segments"]["lan-1"]["bgpAggregations"]["1.1.1.0/27"]["config"]
    assert aggregation == {"prefix": "1.1.1.0/27", "asSet": True, "summaryOnly": True, "id": "1.1.1.0/27"}


def test_build_device_payload_delete_and_detach() -> None:
    mgr = _make_manager()
    config = {
        "segments": [
            {
                "lanSegment": "lan-1",
                "neighbors": [
                    {"remoteIpv4Address": "10.1.1.1", "ipv4InboundFilter": "p1", "ipv4OutboundFilter": "p2"}
                ],
                "bgpAggregations": [{"prefix": "1.1.1.0/27"}],
            }
        ]
    }

    delete_payload = mgr._build_device_payload(config, "delete")
    seg = delete_payload["segments"]["lan-1"]
    assert seg["bgpNeighbors"]["10.1.1.1"] == {"neighbor": None}
    assert seg["bgpAggregations"]["1.1.1.0/27"] == {"config": None}

    detach_payload = mgr._build_device_payload(config, "detach")
    family = detach_payload["segments"]["lan-1"]["bgpNeighbors"]["10.1.1.1"]["neighbor"][
        "addressFamilies"
    ]["ipv4"]["family"]
    assert family["inboundPolicy"] == {"policy": None}
    assert family["outboundPolicy"] == {"policy": None}


def test_build_device_payload_per_entry_state_absent_on_configure() -> None:
    mgr = _make_manager()
    config = {
        "segments": [
            {
                "lanSegment": "lan-1",
                "neighbors": [
                    {"remoteIpv4Address": "10.1.1.1", "peerAs": 65001},
                    {"remoteIpv4Address": "10.1.1.2", "peerAs": 65002, "state": "absent"},
                ],
                "bgpAggregations": [
                    {"prefix": "1.1.1.0/27", "asSet": True},
                    {"prefix": "2.2.2.0/27", "state": "absent"},
                ],
            }
        ]
    }
    seg = mgr._build_device_payload(config, "add")["segments"]["lan-1"]
    assert seg["bgpNeighbors"]["10.1.1.1"]["neighbor"]["peerAsn"] == 65001
    assert seg["bgpNeighbors"]["10.1.1.2"] == {"neighbor": None}
    assert seg["bgpAggregations"]["1.1.1.0/27"]["config"]["asSet"] is True
    assert seg["bgpAggregations"]["2.2.2.0/27"] == {"config": None}


def test_build_device_payload_detach_policy_via_absent_keeps_neighbor() -> None:
    mgr = _make_manager()
    config = {
        "segments": [
            {
                "lanSegment": "lan-1",
                "neighbors": [
                    {
                        "remoteIpv4Address": "10.1.1.1",
                        "peerAs": 65001,
                        "ipv4InboundFilter": "absent",
                        "ipv4OutboundFilter": "keep_me",
                    }
                ],
            }
        ]
    }
    neighbor = mgr._build_device_payload(config, "add")["segments"]["lan-1"]["bgpNeighbors"]["10.1.1.1"]["neighbor"]
    ipv4 = neighbor["addressFamilies"]["ipv4"]["family"]
    assert neighbor["peerAsn"] == 65001
    assert ipv4["inboundPolicy"] == {"policy": None}
    assert ipv4["outboundPolicy"] == {"policy": "keep_me"}
    ipv6 = neighbor["addressFamilies"]["ipv6"]["family"]
    assert "inboundPolicy" not in ipv6
    assert "outboundPolicy" not in ipv6


def test_build_device_payload_missing_policy_raises() -> None:
    mgr = _make_manager()
    mgr.gsdk.get_global_routing_policy_id.return_value = None
    with pytest.raises(ConfigurationError, match="not found"):
        mgr._build_device_payload({"segments": [], "routePolicies": ["missing"]}, "add")


def test_build_device_payload_missing_segments_raises() -> None:
    mgr = _make_manager()
    with pytest.raises(ConfigurationError, match="segments"):
        mgr._build_device_payload({"routePolicies": []}, "add")


def test_build_device_payload_accepts_legacy_snake_case_keys() -> None:
    """Pre-26.9.0 snake_case config keys still work (non-breaking) and match camelCase output."""
    mgr = _make_manager()
    snake = {
        "segments": [
            {
                "lan_segment": "lan-1",
                "neighbors": [
                    {
                        "remote_ipv4_address": "10.1.1.1",
                        "peer_as": 65001,
                        "local_interface": "Gig1",
                        "ipv4_inbound_filter": "p1",
                        "hold_timer": 180,
                        "bfd": True,
                        "minimum_interval": 1200,
                        "local_multiplier": 4,
                    }
                ],
                "bgp_aggregations": [{"prefix": "1.1.1.0/27", "as_set": True, "summary_only": True}],
            }
        ]
    }
    camel = {
        "segments": [
            {
                "lanSegment": "lan-1",
                "neighbors": [
                    {
                        "remoteIpv4Address": "10.1.1.1",
                        "peerAs": 65001,
                        "localInterface": "Gig1",
                        "ipv4InboundFilter": "p1",
                        "holdTimer": 180,
                        "bfd": True,
                        "minimumInterval": 1200,
                        "localMultiplier": 4,
                    }
                ],
                "bgpAggregations": [{"prefix": "1.1.1.0/27", "asSet": True, "summaryOnly": True}],
            }
        ]
    }
    assert mgr._build_device_payload(snake, "add") == mgr._build_device_payload(camel, "add")


def test_camelize_prefers_camelcase_when_both_present() -> None:
    """When a config supplies both forms of a key, the camelCase value wins."""
    out = BGPManager._camelize({"peer_as": 1, "peerAs": 2, "state": "absent"})
    assert out == {"peerAs": 2, "state": "absent"}


# --- absent no-op pruning ---------------------------------------------------

def test_prune_absent_noops_drops_delete_of_missing_targets() -> None:
    """A state: absent entry for something not on the device is pruned (avoids a 500)."""
    mgr = _make_manager()
    # Desired: configure 1.1.1.0/27, delete 2.1.1.0/27 (not on device); keep neighbor 10.1.1.1.
    payload = _desired_payload(
        {
            "segments": [
                {
                    "lanSegment": "lan-1",
                    "neighbors": [{"remoteIpv4Address": "10.1.1.1", "peerAs": 1}],
                    "bgpAggregations": [
                        {"prefix": "1.1.1.0/27", "asSet": True},
                        {"prefix": "2.1.1.0/27", "state": "absent"},
                    ],
                }
            ]
        }
    )
    # Device has neither aggregation yet.
    device_dict = _device_dict(neighbors=[], aggregations=[])
    pruned = mgr._prune_absent_noops(payload, device_dict)
    aggs = pruned["segments"]["lan-1"]["bgpAggregations"]
    assert "2.1.1.0/27" not in aggs          # missing delete target pruned
    assert "1.1.1.0/27" in aggs              # real configure kept


def test_prune_absent_noops_keeps_delete_of_existing_target() -> None:
    """A state: absent entry for something that IS on the device is kept (real delete)."""
    mgr = _make_manager()
    payload = _desired_payload(
        {
            "segments": [
                {
                    "lanSegment": "lan-1",
                    "bgpAggregations": [{"prefix": "2.1.1.0/27", "state": "absent"}],
                }
            ]
        }
    )
    device_dict = _device_dict(aggregations=[{"prefix": "2.1.1.0/27", "asSet": True}])
    pruned = mgr._prune_absent_noops(payload, device_dict)
    assert pruned["segments"]["lan-1"]["bgpAggregations"]["2.1.1.0/27"] == {"config": None}


def test_prune_absent_noops_drops_empty_segment() -> None:
    """A segment whose only content is a pruned no-op delete is removed entirely."""
    mgr = _make_manager()
    payload = _desired_payload(
        {"segments": [{"lanSegment": "lan-1", "neighbors": [{"remoteIpv4Address": "10.9.9.9", "peerAs": 1,
                                                             "state": "absent"}]}]},
        action="add",
    )
    device_dict = _device_dict(neighbors=[])  # neighbor not present
    pruned = mgr._prune_absent_noops(payload, device_dict)
    assert pruned["segments"] == {}


# --- segment-level eBGP multipath -------------------------------------------

def test_build_device_payload_ebgp_multipath_enabled() -> None:
    mgr = _make_manager()
    for value in (True, {"enabled": True}):
        seg = mgr._build_device_payload(
            {"segments": [{"lanSegment": "lan-1", "ebgpMultipath": value}]}, "add"
        )["segments"]["lan-1"]
        assert seg["ebgpMultipath"] == {"config": {"enabled": True}}


def test_build_device_payload_ebgp_multipath_snake_alias() -> None:
    """Legacy ``ebgp_multipath`` key is accepted as an alias."""
    mgr = _make_manager()
    seg = mgr._build_device_payload(
        {"segments": [{"lan_segment": "lan-1", "ebgp_multipath": True}]}, "add"
    )["segments"]["lan-1"]
    assert seg["ebgpMultipath"] == {"config": {"enabled": True}}


def test_build_device_payload_ebgp_multipath_disabled_on_delete() -> None:
    mgr = _make_manager()
    seg = mgr._build_device_payload(
        {"segments": [{"lanSegment": "lan-1", "ebgpMultipath": True}]}, "delete"
    )["segments"]["lan-1"]
    assert seg["ebgpMultipath"] == {"config": {"enabled": False}}


# --- vault MD5 password fill ------------------------------------------------

def test_build_device_payload_vault_fills_md5_when_absent() -> None:
    """Vault fills a neighbor's MD5 when the YAML leaves it null/absent (keyed device -> address)."""
    mgr = _make_manager()
    config = {"segments": [{"lanSegment": "lan-1", "neighbors": [{"remoteIpv4Address": "10.1.1.1", "peerAs": 1}]}]}
    vault = {"edge-1": {"10.1.1.1": "s3cret"}}
    neighbor = mgr._build_device_payload(config, "add", "edge-1", vault)["segments"]["lan-1"][
        "bgpNeighbors"
    ]["10.1.1.1"]["neighbor"]
    assert neighbor["md5Password"] == {"md5Password": "s3cret"}


def test_build_device_payload_yaml_md5_wins_over_vault() -> None:
    """A non-null md5Password in the config always wins over the vault value."""
    mgr = _make_manager()
    config = {
        "segments": [
            {"lanSegment": "lan-1", "neighbors": [{"remoteIpv4Address": "10.1.1.1", "peerAs": 1, "md5Password": "y"}]}
        ]
    }
    vault = {"edge-1": {"10.1.1.1": "s3cret"}}
    neighbor = mgr._build_device_payload(config, "add", "edge-1", vault)["segments"]["lan-1"][
        "bgpNeighbors"
    ]["10.1.1.1"]["neighbor"]
    assert neighbor["md5Password"] == {"md5Password": "y"}


def test_build_device_payload_no_vault_leaves_md5_null() -> None:
    mgr = _make_manager()
    config = {"segments": [{"lanSegment": "lan-1", "neighbors": [{"remoteIpv4Address": "10.1.1.1", "peerAs": 1}]}]}
    neighbor = mgr._build_device_payload(config, "add")["segments"]["lan-1"]["bgpNeighbors"][
        "10.1.1.1"
    ]["neighbor"]
    assert neighbor["md5Password"] == {"md5Password": None}


def test_device_diff_ebgp_multipath_change_only_when_state_differs() -> None:
    mgr = _make_manager()
    payload = _desired_payload({"segments": [{"lanSegment": "lan-1", "ebgpMultipath": True}]}, action="add")

    # Device GET reports multipath under 'bgpMultipath'.
    off = {"segments": [{"name": "lan-1", "bgpMultipath": {"enabled": False}}]}
    assert mgr._device_diff(payload, off, action="add")[0] is True

    on = {"segments": [{"name": "lan-1", "bgpMultipath": {"enabled": True}}]}
    assert mgr._device_diff(payload, on, action="add")[0] is False
