# -*- coding: utf-8 -*-
# Copyright (c) Graphiant, Inc. | GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt)
"""Unit tests for DataAssuranceManager validation helpers (no live API)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ansible_collections.graphiant.naas.plugins.module_utils.libs.data_assurance_manager import (
    DataAssuranceManager,
    _norm_config,
)
from ansible_collections.graphiant.naas.plugins.module_utils.libs.exceptions import ConfigurationError


def _mgr() -> DataAssuranceManager:
    return DataAssuranceManager(MagicMock())


# ---------------------------------------------------------------------------
# _validate_flex_algo
# ---------------------------------------------------------------------------

def test_validate_flex_algo_skips_when_empty() -> None:
    # No exception raised for block/protection policies (empty flexAlgo).
    DataAssuranceManager._validate_flex_algo("", "p1", {"LATENCY": {}})
    DataAssuranceManager._validate_flex_algo(None, "p1", {"LATENCY": {}})


def test_validate_flex_algo_passes_when_present() -> None:
    DataAssuranceManager._validate_flex_algo("LATENCY", "p1", {"LATENCY": {}})


def test_validate_flex_algo_raises_when_missing() -> None:
    with pytest.raises(ConfigurationError) as exc:
        DataAssuranceManager._validate_flex_algo("BOGUS", "p1", {"LATENCY": {}})
    assert "flexAlgo 'BOGUS' does not exist" in str(exc.value)
    assert "p1" in str(exc.value)


# ---------------------------------------------------------------------------
# _validate_lan_names
# ---------------------------------------------------------------------------

def test_validate_lan_names_skips_when_empty() -> None:
    # Empty/omitted lanNames means "all segments" — no validation, no error.
    DataAssuranceManager._validate_lan_names(None, "p1", {"lan-1": 1})
    DataAssuranceManager._validate_lan_names([], "p1", {"lan-1": 1})


def test_validate_lan_names_passes_when_all_present() -> None:
    DataAssuranceManager._validate_lan_names(["lan-1", "lan-2"], "p1", {"lan-1": 1, "lan-2": 2})


def test_validate_lan_names_raises_and_lists_missing() -> None:
    with pytest.raises(ConfigurationError) as exc:
        DataAssuranceManager._validate_lan_names(["lan-1", "nope"], "p1", {"lan-1": 1})
    msg = str(exc.value)
    assert "nope" in msg
    assert "lan-1" not in msg.split("do not exist", maxsplit=1)[0]  # only missing names in the "[...]" list
    assert "Available LAN segments" in msg
    assert "p1" in msg


# ---------------------------------------------------------------------------
# _fetch_valid_lan_segments
# ---------------------------------------------------------------------------

def test_fetch_valid_lan_segments_returns_name_id_map() -> None:
    m = _mgr()
    m.gsdk.get_lan_segments_dict.return_value = {"lan-1": 1, "lan-2": 2}
    assert m._fetch_valid_lan_segments() == {"lan-1": 1, "lan-2": 2}
    m.gsdk.get_lan_segments_dict.assert_called_once()


# ---------------------------------------------------------------------------
# _norm_config — idempotency (boolean flag defaults must not churn)
# ---------------------------------------------------------------------------

def test_norm_config_app_useallservers_absent_equals_false() -> None:
    # An app with explicit servers and no useAllServers (desired) must normalize equal to
    # the stored config the portal echoes back with useAllServers=False — otherwise the
    # policy is re-updated on every run.
    desired = {
        "name": "p2",
        "useAllSites": True,
        "flexAlgo": "test-all-cores",
        "apps": [{"name": "iperf", "bucketId": 1024, "servers": [{"ip": "10.1.1.2", "port": 5201, "protocol": "udp"}]}],
    }
    current = {
        "name": "p2",
        "useAllSites": True,
        "flexAlgo": "test-all-cores",
        "apps": [
            {
                "name": "iperf",
                "bucketId": 1024,
                "isDomain": False,
                "useAllServers": False,
                "servers": [{"ip": "10.1.1.2", "port": 5201, "protocol": "udp"}],
            }
        ],
    }
    assert _norm_config(desired) == _norm_config(current)


def test_norm_config_app_useallservers_true_differs_from_false() -> None:
    desired = {"name": "p", "apps": [{"name": "a", "bucketId": 1, "useAllServers": True}]}
    current = {"name": "p", "apps": [{"name": "a", "bucketId": 1, "useAllServers": False}]}
    assert _norm_config(desired) != _norm_config(current)


def test_norm_config_server_bare_ip_equals_cidr_host() -> None:
    # Bare IP (desired) must normalize equal to the /32 host form the portal echoes back.
    desired = {
        "name": "p2",
        "apps": [{"name": "iperf", "bucketId": 1024, "servers": [{"ip": "10.1.1.2", "port": 5201, "protocol": "udp"}]}],
    }
    current = {
        "name": "p2",
        "apps": [
            {"name": "iperf", "bucketId": 1024, "servers": [{"ip": "10.1.1.2/32", "port": 5201, "protocol": "udp"}]}
        ],
    }
    assert _norm_config(desired) == _norm_config(current)


def test_norm_config_server_real_subnet_preserved() -> None:
    # A genuine subnet mask must not be stripped, so distinct subnets stay distinct.
    a = {"name": "p", "apps": [{"name": "x", "bucketId": 1, "servers": [{"ip": "10.1.1.0/24", "port": 1}]}]}
    b = {"name": "p", "apps": [{"name": "x", "bucketId": 1, "servers": [{"ip": "10.1.1.0", "port": 1}]}]}
    assert _norm_config(a) != _norm_config(b)
