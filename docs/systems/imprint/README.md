# Imprint — pointing an agent app on this Mac at nOS

The imprint is the one page a new model reads first: `IMPRINT.md` at the repo
root. It is rendered by `tools/imprint-gen.py` and gated by
`tests/anatomy/test_imprint_is_rendered.py`; never edit it by hand.

## Point an external agent app (e.g. OpenHuman) at nOS

1. **First page.** Give the app `<repo>/IMPRINT.md` as its system or context file.
2. **The tables (MCP, stdio).** Register this command as an MCP server:

   ```
   KEAP_API_URL=http://127.0.0.1:8091 \
   KEAP_AGENT_TOKEN_RO=<value of keap_agent_token_ro in ~/.nos/secrets.yml> \
   NOS_MCP_AGENT=openhuman \
   python3 <repo>/tools/mcp-tables-server.py
   ```

   `~/.nos/secrets.yml` (mode 0600) is written by the converge from
   `templates/secrets.yml.j2`; the port is `keap_port`. The RO token reads only;
   a write verb answers 401/403 — that is correct. **The RW token
   (`keap_agent_token_rw`) is never given to an end-user app**: writes stay
   with the operator and the estate's own agents. Offline check: `--selftest`.
3. **Local models.** Ollama's OpenAI-compatible surface: `http://127.0.0.1:11434/v1`,
   no token (`state/llm-backends.yml`, row `ollama`).
4. **Web.** Services answer at `<name>.<tenant_domain>` through Traefik; ask
   `tools/estate-status.py --config tenant_domain` for this host's value.

## Measure it (Apgar)

The operator runs this; it loads a local model and costs memory on this host.

```
tools/apgar.py ask --imprint IMPRINT.md --model ollama:<model> --out newborn.json
tools/apgar.py ask --no-imprint --model ollama:<model> --out control.json
tools/apgar.py score newborn.json --control control.json
```

The lift (score minus control) is what the imprint bought. An `openhuman`
adapter for `tools/apgar.py` is a separate roadmap row, not built here.
