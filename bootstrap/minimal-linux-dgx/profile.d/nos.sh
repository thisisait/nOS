# /etc/profile.d/nos.sh — nOS on the DGX: tokens and addresses for every shell.
# Files are group-readable by design: keap.env for nos-users (read-only token),
# keap-rw.env for nos-maintainers (write token + proxy secret). Sourcing a
# file you cannot read is silently skipped, so a user gets exactly their tier.
for _f in /etc/nos/keap.env /etc/nos/keap-rw.env; do
  [ -r "$_f" ] && { set -a; . "$_f"; set +a; }
done
unset _f
# Native Ollama listens on the docker0 address so containers reach it too.
export OLLAMA_HOST="${OLLAMA_HOST:-http://172.17.0.1:11434}"
export NOS_SRC="${NOS_SRC:-/srv/nos}"
