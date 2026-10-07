# Ollama — the local model runtime

Ollama serves the estate's local models on `127.0.0.1:11434`: the host-safe
chat model (`ollama_small_model`, hermes3:8b) and the embedding model
(`nomic-embed-text`) that KEAP's `keap-embed-sync` job uses. It is a
**self** organ: nOS installs the Homebrew formula, pins `ollama_version`,
and starts it under launchd as `com.ollama.agent` (`roles/pazny.ollama`).

- Toggle: `install_ollama` (default on; CI turns it off).
- Loopback only; Traefik routes nothing. A second Ollama on the habitat is
  RED in `tools/openhuman-status.py`.
- Consumers declare it: openclaw, hermes, keap, openhuman (`depends_on` in
  their plugins); core cells reach it as `backend:ollama`
  (`state/habitat/llm-backends.yml`).
- A resident 14B model starves KEAP (memory `local-model-budget`); the
  converge unloads resident models before core-up.
