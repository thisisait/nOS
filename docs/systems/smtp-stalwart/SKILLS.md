# Stalwart Mail — Skills

> Callable actions for Stalwart. Administration is JMAP over loopback; mail transport is standard SMTP/IMAP.

## Authentication

- **JMAP admin:** basic auth as `admin` / `{global_password_prefix}_pw_stalwart_admin` against `http://127.0.0.1:8088/jmap` (loopback only).
- **Mail transport:** SASL with a mailbox user's SMTP/IMAP credentials from Stalwart's own user DB.
- No bearer token is issued; there is no OIDC on the mail protocols.

---

## provision-mailbox

**Trigger:** "create a mailbox", "add a mail user", "provision an email account"
**Method:** JMAP
**Endpoint:** `POST http://127.0.0.1:8088/jmap`
**Input:** a JMAP request whose `methodCalls` carry `Principal/set` with the new principal (this is the exact path Wing's `App\Model\StalwartProvisioner` uses for invite-driven provisioning).
**Output:** the JMAP response with the created/updated principal id.

---

## list-principals

**Trigger:** "list mailboxes", "show mail accounts", "which users have email"
**Method:** JMAP
**Endpoint:** `POST http://127.0.0.1:8088/jmap`
**Input:** `methodCalls` with `Principal/get` (optionally `Principal/query`).
**Output:** the set of mail principals and their attributes.

---

## send-mail

**Trigger:** "send an email", "deliver a message via Stalwart"
**Method:** SMTP submission
**Endpoint:** host `587` (STARTTLS) or `465` (implicit TLS)
**Input:** authenticate with a mailbox user's SASL credentials, then submit the message.
**Output:** SMTP `250` acceptance (message enters Stalwart's queue for delivery).

---

## read-mailbox

**Trigger:** "read a mailbox", "fetch inbox over IMAP", "check received mail"
**Method:** IMAPS
**Endpoint:** host `993`
**Input:** SASL login as the mailbox user.
**Output:** IMAP folder/message listing.
