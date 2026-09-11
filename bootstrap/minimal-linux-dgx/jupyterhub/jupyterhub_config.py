# =============================================================================
# nos-dgx — JupyterHub: one Lab per Linux user, as that user, PAM login.
#
# Why a Hub and not a Lab: the box is multi-user, and the Hub's default
# authenticator IS PAM against the local accounts — the same roster nginx
# already gates KEAP with (group nos-users). LocalProcessSpawner runs each
# single-user server setuid AS the user in their home, so isolation is the
# kernel's, not a config's. nginx gives it TLS only (port 8445): the Hub's
# cookie/token auth would collide with HTTP basic-auth on the Authorization
# header exactly as Open WebUI's did.
#
# Installed by setup-root.sh: venv + configurable-http-proxy ROOT-OWNED under
# /opt/nos-dgx/jupyterhub (root executes them, so a maintainer-writable tree
# would be a root escalation), state root-only under /var/lib/nos-dgx/jupyterhub,
# this file at /etc/nos/jupyterhub_config.py, systemd unit jupyterhub.service.
# =============================================================================
import grp
import os
import pwd

J = "/opt/nos-dgx/jupyterhub"          # venv + chp, root-owned (root runs the Hub)
STATE = "/var/lib/nos-dgx/jupyterhub"  # db, cookie secret, pid — root 0700
c = get_config()  # noqa: F821 — provided by JupyterHub

# ── bind: loopback only, nginx is the edge ───────────────────────────────────
c.JupyterHub.bind_url = "http://127.0.0.1:8010"   # 8000 is the loopback door to Ollama (NemoClaw)
c.JupyterHub.hub_ip = "127.0.0.1"
c.JupyterHub.hub_port = 8081
c.ConfigurableHTTPProxy.command = [f"{J}/chp/node_modules/.bin/configurable-http-proxy"]
c.ConfigurableHTTPProxy.api_url = "http://127.0.0.1:8001"

# ── state: root-only dir, survives upgrades of the venv ──────────────────────
c.JupyterHub.db_url = f"sqlite:///{STATE}/jupyterhub.sqlite"
c.JupyterHub.cookie_secret_file = f"{STATE}/jupyterhub_cookie_secret"
c.JupyterHub.pid_file = f"{STATE}/jupyterhub.pid"
# A Hub restart (upgrade, config reload) must not kill running notebooks.
c.JupyterHub.cleanup_servers = False

# ── who may log in: the box's own accounts, group-gated like nginx ───────────
c.JupyterHub.authenticator_class = "pam"
c.PAMAuthenticator.service = "login"
c.PAMAuthenticator.open_sessions = False
c.LocalAuthenticator.allowed_groups = {"nos-users"}
c.LocalAuthenticator.create_system_users = False
c.Authenticator.admin_users = {"admin"}

# ── the single-user server: from the shared venv, as the user, in $HOME ──────
c.JupyterHub.spawner_class = "localprocess"
c.Spawner.cmd = [f"{J}/venv/bin/jupyterhub-singleuser"]
c.Spawner.default_url = "/lab"
c.Spawner.notebook_dir = "~"
c.Spawner.http_timeout = 120
c.Spawner.start_timeout = 120
# Shared kernel from the venv; users add their own with
#   python -m ipykernel install --user --name <env>
c.Spawner.environment = {
    "NOS_SRC": "/srv/nos",
    "KEAP_API_URL": "http://127.0.0.1:8091",
    "OLLAMA_HOST": "http://172.17.0.1:11434",
    "PATH": f"{J}/venv/bin:/usr/local/bin:/usr/bin:/bin",
}


def _tiered_tokens(spawner):
    """Hand each Lab the KEAP tokens its user may read — and only those.

    The Hub runs as root, so it can read /etc/nos/*.env; the spawned server
    runs as the user, who could `source` the same files in a terminal anyway.
    This just mirrors /etc/profile.d/nos.sh, which a spawned process never
    sources: nos-users get the RO token, nos-maintainers additionally RW.
    """
    user = spawner.user.name
    try:
        groups = {g.gr_name for g in grp.getgrall() if user in g.gr_mem}
        groups.add(grp.getgrgid(pwd.getpwnam(user).pw_gid).gr_name)
    except KeyError:
        return
    files = []
    if "nos-users" in groups:
        files.append("/etc/nos/keap.env")
    if "nos-maintainers" in groups:
        files.append("/etc/nos/keap-rw.env")
    env = dict(spawner.environment)
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env[k] = v
        except OSError:
            pass
    spawner.environment = env


c.Spawner.pre_spawn_hook = _tiered_tokens

# ── quality of life ──────────────────────────────────────────────────────────
c.JupyterHub.shutdown_on_logout = False
c.JupyterHub.last_activity_interval = 300
