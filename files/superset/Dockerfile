# =============================================================================
# nOS Superset — custom image
#
# Motivation: apache/superset:6.0.0-dev bundles psycopg2 and flask_appbuilder
# but NOT `authlib`, which is required by our superset_config.py to implement
# OIDC against Authentik (AUTH_TYPE = AUTH_OAUTH + OAUTH_PROVIDERS). Without
# authlib the container crash-loops with
#
#     ModuleNotFoundError: No module named 'authlib'
#
# We layer it in on top of the official upstream image. Base tag is parameter-
# ized via BASE build-arg so the role default (superset_version) drives the
# exact upstream revision.
# =============================================================================
ARG BASE=apache/superset:6.0.0-dev
FROM ${BASE}

USER root
# Install directly into Superset's venv (/app/.venv) so the already-active
# Python interpreter sees the new packages. `uv pip install --system` would
# target the system interpreter which Superset does not use.
# nos_build_ca (optional BuildKit secret): a TLS-intercepting proxy's CA,
# trusted for this download only — it never lands in a layer.
RUN --mount=type=secret,id=nos_build_ca,required=false \
    if [ -s /run/secrets/nos_build_ca ]; then export PIP_CERT=/run/secrets/nos_build_ca; fi; \
    /app/.venv/bin/pip install --no-cache-dir \
        "authlib>=1.3" \
 && rm -rf /root/.cache/pip /root/.cache/uv
USER superset
