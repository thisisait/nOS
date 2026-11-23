# Santa — exec telemetry in MONITOR mode

Santa (northpolesec, Apache-2.0) is a macOS Endpoint Security client. nOS runs
it in **MONITOR mode only**: it allows every exec and logs it to
`/var/db/santa/santa.log`. It is a **symbiont** organ: vendor software that nOS
installs from a sha256-pinned release pkg (`santa_version`, `santa_pkg_sha256`)
in `roles/pazny.santa`.

- Toggle: `install_santa` (default off; macOS only). Converge: `nos --tags santa`.
- No configuration profile and no rules are rendered, so ClientMode stays 1
  (Monitor); the role stops if anything else set a mode
  (`tests/anatomy/test_santa_is_monitor_only.py`).
- The system extension and Full Disk Access need a human click in System
  Settings; the role stops with the steps until they are given.
- Four vendor launchd jobs: `com.northpolesec.santa` (LaunchAgent) and the
  `.bundleservice`, `.metricservice`, `.syncservice` LaunchDaemons. The role
  declares them (`santa_*_launchd_label`), so they are the santa row's jobs, not
  undeclared, and `install_santa: false` on disk boots them out.
- Reader: `tools/santa-status.py` judges EXEC lines against the trees nOS
  declares and reports what ran elsewhere. Red: declared but absent, a mode
  other than Monitor, any DENY.
- GDPR: `files/anatomy/plugins/santa-base/plugin.yml` (exec telemetry, host only).
