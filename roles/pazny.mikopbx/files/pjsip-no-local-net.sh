#!/bin/sh
# nOS (pazny.mikopbx) — MikoPBX custom-files script for /etc/asterisk/pjsip.conf.
# Docker Desktop (macOS) delivers every published UDP packet from the bridge
# gateway, which sits inside Asterisk's local_net, so SDP would carry the
# container IP and calls have no audio. Advertise the external address to all.
sed -i '/^local_net=/d' "$1"
