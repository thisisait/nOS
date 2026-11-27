#!/usr/bin/env bash
# Read-only probe of the :443 TLS floor: two handshakes against 127.0.0.1, nothing sent.
# Usage: tls-floor-probe.sh <port> <sni> <VersionTLS12|VersionTLS13>
# Exit 0 = the edge matches the floor, 1 = it does not, 2 = UNKNOWN (could not probe).
port=$1 sni=$2 floor=$3
hs() { openssl s_client "$1" -connect "127.0.0.1:${port}" -servername "${sni}" </dev/null >/dev/null 2>&1; }
where="127.0.0.1:${port} sni=${sni} floor=${floor}"
if ! command -v openssl >/dev/null 2>&1; then
  echo "UNKNOWN ${where}: no openssl client on this host"; exit 2
fi
# The 1.3 handshake is the control: without it a refused 1.2 proves nothing.
if ! hs -tls1_3; then
  echo "UNKNOWN ${where}: TLS 1.3 handshake failed (port closed, no TLS, or client lacks -tls1_3)"; exit 2
fi
if hs -tls1_2; then t12=accepted; else t12=refused; fi
echo "${where}: TLS 1.2 ${t12}, TLS 1.3 accepted"
case "${floor}:${t12}" in
  VersionTLS13:refused|VersionTLS12:accepted) exit 0 ;;
  *) exit 1 ;;
esac
