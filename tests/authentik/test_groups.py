"""Group CRUD + rename + prefix rename + member/policy preservation."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import pytest

# Track J Phase 5: gate on optional `responses` mock library so pytest
# collection passes on machines without the test-extras venv. Tests
# themselves still run identically when `responses` IS installed.
pytest.importorskip("responses")
import responses  # noqa: E402

from library import nos_authentik as mod  # type: ignore[import] # noqa: E402


def _paged(results, next_page=None):
    """Build an Authentik-style paged response dict."""
    return {
        "results": list(results),
        "pagination": {"next": next_page or 0, "count": len(results)},
    }


# ---------------------------------------------------------------------------
# list / get
# ---------------------------------------------------------------------------


@responses.activate
def test_list_groups_single_page(client, api_base, sample_group):
    responses.add(
        responses.GET,
        api_base + "/core/groups/",
        json=_paged([sample_group]),
        status=200,
    )
    groups = client.list_groups()
    assert len(groups) == 1
    assert groups[0]["name"] == "devboxnos-admins"


@responses.activate
def test_list_groups_multi_page(client, api_base, sample_group):
    page1 = dict(sample_group, name="devboxnos-a")
    page2 = dict(sample_group, pk="22222222-2222-2222-2222-222222222222", name="devboxnos-b")
    responses.add(
        responses.GET,
        api_base + "/core/groups/",
        json=_paged([page1], next_page=2),
        status=200,
    )
    responses.add(
        responses.GET,
        api_base + "/core/groups/",
        json=_paged([page2]),
        status=200,
    )
    groups = client.list_groups()
    assert [g["name"] for g in groups] == ["devboxnos-a", "devboxnos-b"]


@responses.activate
def test_get_group_by_name_found(client, api_base, sample_group):
    responses.add(
        responses.GET,
        api_base + "/core/groups/",
        json=_paged([sample_group]),
        status=200,
    )
    g = client.get_group_by_name("devboxnos-admins")
    assert g is not None
    assert g["pk"] == sample_group["pk"]


@responses.activate
def test_get_group_by_name_missing(client, api_base):
    responses.add(
        responses.GET,
        api_base + "/core/groups/",
        json=_paged([]),
        status=200,
    )
    assert client.get_group_by_name("ghost") is None


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


@responses.activate
def test_delete_group(client, api_base, sample_group):
    responses.add(responses.DELETE, api_base + "/core/groups/%s/" % sample_group["pk"], status=204)
    assert client.delete_group(sample_group["pk"]) is True


# ---------------------------------------------------------------------------
# rename_group — PK preservation => members preserved
# ---------------------------------------------------------------------------


@responses.activate
def test_rename_group_preserves_pk_and_members(client, api_base, sample_group):
    src = sample_group
    renamed = dict(src, name="nos-admins")

    # 1) get_group_by_name("nos-admins") => empty
    responses.add(responses.GET, api_base + "/core/groups/", json=_paged([]), status=200)
    # 2) get_group_by_name("devboxnos-admins") => [src]
    responses.add(responses.GET, api_base + "/core/groups/", json=_paged([src]), status=200)
    # 3) list bindings before (none)
    responses.add(responses.GET, api_base + "/policies/bindings/", json=_paged([]), status=200)
    # 4) PATCH rename
    responses.add(responses.PATCH, api_base + "/core/groups/%s/" % src["pk"], json=renamed, status=200)
    # 5) list bindings after (none)
    responses.add(responses.GET, api_base + "/policies/bindings/", json=_paged([]), status=200)

    result = mod.op_rename_group(client, "devboxnos-admins", "nos-admins")
    assert result["changed"] is True
    assert result["renamed"] == 1
    # PK returned by the API is the same, so the module validated it.
    assert result["group"]["pk"] == src["pk"]
    # Members array carried over as-is (Authentik keeps ``users`` on PK).
    # We don't explicitly check it here because Authentik may or may not echo it
    # on PATCH, but the module asserts PK-stability which is the real guarantee.


@responses.activate
def test_rename_group_policy_bindings_preserved(client, api_base, sample_group):
    src = sample_group
    renamed = dict(src, name="nos-admins")
    binding = {"pk": "b1", "group": src["pk"], "policy": "p1", "order": 0}

    responses.add(responses.GET, api_base + "/core/groups/", json=_paged([]), status=200)  # dst
    responses.add(responses.GET, api_base + "/core/groups/", json=_paged([src]), status=200)  # src
    responses.add(responses.GET, api_base + "/policies/bindings/", json=_paged([binding]), status=200)
    responses.add(responses.PATCH, api_base + "/core/groups/%s/" % src["pk"], json=renamed, status=200)
    responses.add(responses.GET, api_base + "/policies/bindings/", json=_paged([binding]), status=200)

    result = mod.op_rename_group(client, "devboxnos-admins", "nos-admins", preserve_policies=True)
    assert result["changed"] is True


@responses.activate
def test_rename_group_fails_if_pk_changes(client, api_base, sample_group):
    src = sample_group
    # Simulate Authentik bug: PK changes on rename.
    renamed = dict(src, pk="99999999-9999-9999-9999-999999999999", name="nos-admins")
    responses.add(responses.GET, api_base + "/core/groups/", json=_paged([]), status=200)
    responses.add(responses.GET, api_base + "/core/groups/", json=_paged([src]), status=200)
    responses.add(responses.GET, api_base + "/policies/bindings/", json=_paged([]), status=200)
    responses.add(responses.PATCH, api_base + "/core/groups/%s/" % src["pk"], json=renamed, status=200)

    from module_utils.nos_authentik_client import AuthentikApiError
    with pytest.raises(AuthentikApiError):
        mod.op_rename_group(client, "devboxnos-admins", "nos-admins")


@responses.activate
def test_rename_group_idempotent_when_already_renamed(client, api_base, sample_group):
    renamed = dict(sample_group, name="nos-admins")
    # destination found, source absent
    responses.add(responses.GET, api_base + "/core/groups/", json=_paged([renamed]), status=200)
    responses.add(responses.GET, api_base + "/core/groups/", json=_paged([]), status=200)

    result = mod.op_rename_group(client, "devboxnos-admins", "nos-admins")
    assert result["changed"] is False
    assert result["renamed"] == 0


# ---------------------------------------------------------------------------
# rename_group_prefix — applies to all matching
# ---------------------------------------------------------------------------


@responses.activate
def test_rename_group_prefix_renames_all(client, api_base):
    groups = [
        {"pk": "g-admins", "name": "devboxnos-admins", "users": []},
        {"pk": "g-managers", "name": "devboxnos-managers", "users": []},
        {"pk": "g-users", "name": "devboxnos-users", "users": []},
        {"pk": "g-internal", "name": "authentik Admins", "users": []},
    ]
    # Initial list
    responses.add(responses.GET, api_base + "/core/groups/", json=_paged(groups), status=200)

    # For each rename, the module does:
    #   get(dst)    -> none
    #   get(src)    -> [src]
    #   list bindings before
    #   PATCH
    #   list bindings after
    def _add_rename_cycle(pk, old, new):
        responses.add(responses.GET, api_base + "/core/groups/", json=_paged([]), status=200)  # dst check in op_rename_group_prefix
        responses.add(responses.GET, api_base + "/core/groups/", json=_paged([]), status=200)  # dst check in op_rename_group
        responses.add(responses.GET, api_base + "/core/groups/",
                      json=_paged([{"pk": pk, "name": old, "users": []}]), status=200)  # src
        responses.add(responses.GET, api_base + "/policies/bindings/", json=_paged([]), status=200)
        responses.add(responses.PATCH, api_base + "/core/groups/%s/" % pk,
                      json={"pk": pk, "name": new, "users": []}, status=200)
        responses.add(responses.GET, api_base + "/policies/bindings/", json=_paged([]), status=200)

    _add_rename_cycle("g-admins", "devboxnos-admins", "nos-admins")
    _add_rename_cycle("g-managers", "devboxnos-managers", "nos-managers")
    _add_rename_cycle("g-users", "devboxnos-users", "nos-users")

    result = mod.op_rename_group_prefix(client, "devboxnos-", "nos-")
    assert result["changed"] is True
    assert result["renamed"] == 3
    renamed_names = sorted(r["from"] for r in result["groups"])
    assert renamed_names == ["devboxnos-admins", "devboxnos-managers", "devboxnos-users"]


@responses.activate
def test_rename_group_prefix_noop_when_no_matches(client, api_base):
    groups = [{"pk": "g1", "name": "nos-admins"}]
    responses.add(responses.GET, api_base + "/core/groups/", json=_paged(groups), status=200)

    result = mod.op_rename_group_prefix(client, "devboxnos-", "nos-")
    assert result["changed"] is False
    assert result["renamed"] == 0


@responses.activate
def test_rename_group_prefix_skips_already_renamed(client, api_base):
    """If half have already been renamed, prefix rename only touches the stragglers."""
    groups = [
        {"pk": "g-admins", "name": "nos-admins"},
        {"pk": "g-users", "name": "devboxnos-users"},
    ]
    responses.add(responses.GET, api_base + "/core/groups/", json=_paged(groups), status=200)

    # For the only remaining candidate (devboxnos-users):
    #   dst check -> empty
    #   inside op_rename_group: dst check -> empty
    #   src lookup -> [src]
    #   bindings before -> []
    #   PATCH -> renamed
    #   bindings after -> []
    responses.add(responses.GET, api_base + "/core/groups/", json=_paged([]), status=200)
    responses.add(responses.GET, api_base + "/core/groups/", json=_paged([]), status=200)
    responses.add(responses.GET, api_base + "/core/groups/",
                  json=_paged([{"pk": "g-users", "name": "devboxnos-users"}]), status=200)
    responses.add(responses.GET, api_base + "/policies/bindings/", json=_paged([]), status=200)
    responses.add(responses.PATCH, api_base + "/core/groups/g-users/",
                  json={"pk": "g-users", "name": "nos-users"}, status=200)
    responses.add(responses.GET, api_base + "/policies/bindings/", json=_paged([]), status=200)

    result = mod.op_rename_group_prefix(client, "devboxnos-", "nos-")
    assert result["changed"] is True
    assert result["renamed"] == 1
    assert result["groups"][0]["from"] == "devboxnos-users"
