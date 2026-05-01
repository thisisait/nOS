"""OIDC client rename — Application + Provider pair, binding preserved."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import pytest

# Track J Phase 5: gate on optional `responses` mock library.
pytest.importorskip("responses")
import responses  # noqa: E402

from library import nos_authentik as mod  # type: ignore[import] # noqa: E402


def _paged(results, next_page=None):
    return {"results": list(results), "pagination": {"next": next_page or 0}}


@responses.activate
def test_rename_oidc_client_renames_both_app_and_provider(
    client, api_base, sample_provider, sample_application
):
    # op_rename_oidc_client pre-flight checks:
    #   app(to_name) -> None
    #   provider(to_name) -> None
    responses.add(responses.GET, api_base + "/core/applications/", json=_paged([]), status=200)
    responses.add(responses.GET, api_base + "/providers/oauth2/", json=_paged([]), status=200)
    # _find_oidc_pair:
    #   app(from_name)
    responses.add(responses.GET, api_base + "/core/applications/",
                  json=_paged([sample_application]), status=200)
    #   provider(from_name)
    responses.add(responses.GET, api_base + "/providers/oauth2/",
                  json=_paged([sample_provider]), status=200)
    # PATCH provider rename
    renamed_provider = dict(sample_provider, name="nos-grafana")
    responses.add(responses.PATCH, api_base + "/providers/oauth2/%s/" % sample_provider["pk"],
                  json=renamed_provider, status=200)
    # PATCH application rename (only name — provider FK untouched)
    renamed_app = dict(sample_application, name="nos-grafana")
    responses.add(responses.PATCH,
                  api_base + "/core/applications/%s/" % sample_application["slug"],
                  json=renamed_app, status=200)
    # Post-rename verification: lookup by new name — returns app with same provider FK
    responses.add(responses.GET, api_base + "/core/applications/",
                  json=_paged([renamed_app]), status=200)

    result = mod.op_rename_oidc_client(client, "devboxnos-grafana", "nos-grafana")
    assert result["changed"] is True
    assert result["renamed"] == 1

    # Inspect the PATCH bodies to confirm we only touched ``name`` on the app,
    # NOT the provider FK. This is how the binding is preserved.
    patch_calls = [c for c in responses.calls if c.request.method == "PATCH"]
    app_patch = [c for c in patch_calls if "/core/applications/" in c.request.url][0]
    import json as _json
    payload = _json.loads(app_patch.request.body)
    assert payload == {"name": "nos-grafana"}
    assert "provider" not in payload


@responses.activate
def test_rename_oidc_client_idempotent_when_already_renamed(client, api_base):
    renamed_app = {"pk": "a1", "name": "nos-grafana", "slug": "grafana", "provider": 42}
    renamed_prov = {"pk": 42, "name": "nos-grafana"}
    # dst found (both)
    responses.add(responses.GET, api_base + "/core/applications/",
                  json=_paged([renamed_app]), status=200)
    responses.add(responses.GET, api_base + "/providers/oauth2/",
                  json=_paged([renamed_prov]), status=200)
    # src lookup -> empty
    responses.add(responses.GET, api_base + "/core/applications/", json=_paged([]), status=200)
    responses.add(responses.GET, api_base + "/providers/oauth2/", json=_paged([]), status=200)

    result = mod.op_rename_oidc_client(client, "devboxnos-grafana", "nos-grafana")
    assert result["changed"] is False
    assert result["renamed"] == 0


@responses.activate
def test_rename_oidc_client_prefix_renames_all(client, api_base):
    providers = [
        {"pk": 10, "name": "devboxnos-grafana", "client_id": "grafana"},
        {"pk": 11, "name": "devboxnos-portainer", "client_id": "portainer"},
    ]
    apps = [
        {"pk": "app1", "name": "devboxnos-grafana", "slug": "grafana", "provider": 10},
        {"pk": "app2", "name": "devboxnos-portainer", "slug": "portainer", "provider": 11},
    ]

    # Initial inventory (in op_rename_oidc_client_prefix):
    #   list_oauth2_providers
    responses.add(responses.GET, api_base + "/providers/oauth2/", json=_paged(providers), status=200)
    #   list_applications
    responses.add(responses.GET, api_base + "/core/applications/", json=_paged(apps), status=200)

    # For each candidate: op_rename_oidc_client
    def _add_one(app, prov, new_name):
        # dst lookups both empty
        responses.add(responses.GET, api_base + "/core/applications/", json=_paged([]), status=200)
        responses.add(responses.GET, api_base + "/providers/oauth2/", json=_paged([]), status=200)
        # src app
        responses.add(responses.GET, api_base + "/core/applications/", json=_paged([app]), status=200)
        # src provider
        responses.add(responses.GET, api_base + "/providers/oauth2/", json=_paged([prov]), status=200)
        # PATCH provider
        responses.add(responses.PATCH, api_base + "/providers/oauth2/%s/" % prov["pk"],
                      json=dict(prov, name=new_name), status=200)
        # PATCH app
        responses.add(responses.PATCH, api_base + "/core/applications/%s/" % app["slug"],
                      json=dict(app, name=new_name), status=200)
        # Binding check: lookup renamed app
        responses.add(responses.GET, api_base + "/core/applications/",
                      json=_paged([dict(app, name=new_name)]), status=200)

    # Sorted order of candidates: devboxnos-grafana, devboxnos-portainer
    _add_one(apps[0], providers[0], "nos-grafana")
    _add_one(apps[1], providers[1], "nos-portainer")

    result = mod.op_rename_oidc_client_prefix(client, "devboxnos-", "nos-")
    assert result["changed"] is True
    assert result["renamed"] == 2
    assert sorted(c["from"] for c in result["clients"]) == [
        "devboxnos-grafana", "devboxnos-portainer",
    ]
