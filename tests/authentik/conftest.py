"""Shared pytest fixtures + sys.path wiring for the nos_authentik test suite."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
import sys

import pytest

# Ensure the playbook root is on sys.path so ``module_utils.nos_authentik_client``
# and the ``library.nos_authentik`` module resolve the same way Ansible sees them.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


@pytest.fixture
def api_base():
    return "http://127.0.0.1:9003/api/v3"


@pytest.fixture
def client(api_base):
    """Fresh client with a predictable token — fast retry to keep tests snappy."""
    from module_utils.nos_authentik_client import NosAuthentikClient
    return NosAuthentikClient(
        base_url=api_base,
        token="test-token-abc",
        timeout=2,
        retries=3,
        backoff=0.01,
        verify_tls=False,
    )


@pytest.fixture
def sample_group():
    return {
        "pk": "11111111-1111-1111-1111-111111111111",
        "name": "devboxnos-admins",
        "is_superuser": True,
        "attributes": {},
        "users": [1, 2, 3],
    }


@pytest.fixture
def sample_provider():
    return {
        "pk": 42,
        "name": "devboxnos-grafana",
        "client_id": "grafana-client",
    }


@pytest.fixture
def sample_application(sample_provider):
    return {
        "pk": "app-pk-001",
        "name": "devboxnos-grafana",
        "slug": "grafana",
        "provider": sample_provider["pk"],
    }
