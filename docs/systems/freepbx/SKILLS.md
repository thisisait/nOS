# FreePBX — Skills

> **No external skill surface.** nOS provisions no agent-invocable API for FreePBX.

FreePBX is administered through its self-managed PHP web UI and, at the protocol
level, speaks SIP / IAX2 / RTP for real-time voice. None of these is an
agent-callable REST endpoint:

- The FreePBX **GraphQL/REST API** exists upstream but is **not enabled or
  configured** by the playbook, and no API credential or token is provisioned.
- **SIP (5060)**, **IAX2 (4569)** and **RTP (10000-10100)** are real-time voice
  signaling/media protocols, not request/response actions an agent invokes.
- The **admin web UI** uses an interactive PHP session established through the
  first-boot wizard; there is no headless auth an agent could hold.

There are therefore **no `**Trigger:**`-led skills** to declare. Administration
is done by a human in the web UI, or via the `asterisk` CLI inside the container
(`docker exec voip-freepbx-1 asterisk -rx "<command>"`) — a host-shell action,
not a service API.

If a FreePBX API surface is later enabled and credentialed by the playbook, add
the real endpoints here; until then, inventing one would send an agent to a dead
endpoint.
