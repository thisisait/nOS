# tools/cloud/env.sh — source me. The frozen toolchain, wired for this shell.
#
#   . tools/cloud/env.sh
#
# Written by nobody at runtime: every value is DERIVED here, so a session that
# sources it gets the same answer bootstrap.sh would. Safe to source twice.
#
#   ANSIBLE_HOME               .ci-venv/ansible-home (collections from the lock)
#   PATH                       .ci-venv/bin first (ansible-core from ci-freeze.env)
#   NOS_MODULE_PYTHON          the DISTRO python — the one with apt_pkg. The
#                              module side runs apt/dpkg tasks; the venv python
#                              cannot import apt_pkg (python3-apt is a distro
#                              package built for exactly one interpreter), and
#                              /usr/bin/python3 may be an alternatives link to a
#                              different minor (it is 3.11 in the cloud image,
#                              whose apt_pkg is built for 3.12).
#   ANSIBLE_PYTHON_INTERPRETER = NOS_MODULE_PYTHON
#   NOS_TEST_PROVIDES          the pytest environment contract (same as CI)

_nos_repo="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"

nos_find_module_python() {
  local p
  for p in /usr/bin/python3 /usr/bin/python3.[0-9]*; do
    case "$p" in *-config) continue ;; esac
    [ -x "$p" ] || continue
    if "$p" -c 'import apt_pkg' >/dev/null 2>&1; then
      echo "$p"; return 0
    fi
  done
  command -v python3
}

export ANSIBLE_HOME="${_nos_repo}/.ci-venv/ansible-home"
case ":${PATH}:" in
  *":${_nos_repo}/.ci-venv/bin:"*) ;;
  *) export PATH="${_nos_repo}/.ci-venv/bin:${PATH}" ;;
esac
NOS_MODULE_PYTHON="$(nos_find_module_python)"
export NOS_MODULE_PYTHON
export ANSIBLE_PYTHON_INTERPRETER="${NOS_MODULE_PYTHON}"
# The estate's own names must never leave the box. The sandbox routes every
# HTTPS request through an egress proxy (HTTPS_PROXY), whose NO_PROXY knows
# nothing of *.dev.local — so nos-smoke asked the PROXY for auth.dev.local and
# got 403 (measured 2026-09-25). Tenant domain from NOS_E2E_TLD, default dev.local.
_nos_tld="${NOS_E2E_TLD:-dev.local}"
for _v in NO_PROXY no_proxy; do
  case ",$(eval echo "\${$_v:-}")," in
    *",.${_nos_tld},"*) ;;
    *) eval "export $_v=\"\${$_v:+\${$_v},}.${_nos_tld},${_nos_tld}\"" ;;
  esac
done
unset _nos_tld _v
export NOS_TEST_PROVIDES="git,ansible-playbook,php,composer,jq,sqlite3,openssl,files/anatomy/wing/vendor/autoload.php"
unset _nos_repo
