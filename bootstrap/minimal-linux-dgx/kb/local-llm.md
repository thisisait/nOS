---
title: Local models (Ollama)
section: dev
order: 4
summary: Where the model server listens, which models are loaded, and how to point Chat, a notebook or your editor at it.
---

Ollama runs natively as a system service and serves the GPU to everyone. It
listens on the Docker bridge address only — reachable from the DGX and from
containers, **not** from the LAN (the API has no authentication).

| From | Address |
|---|---|
| a shell or notebook on the DGX | `http://172.17.0.1:11434` (already in `OLLAMA_HOST`) |
| a container (yours or the stack's) | `http://host.docker.internal:11434` |
| your laptop | not directly — use Chat, or an SSH tunnel: `ssh -L 11434:172.17.0.1:11434 <you>@__HOST__` |

```
ollama list                 # installed models
ollama ps                   # what is loaded right now, and on which device
curl -s $OLLAMA_HOST/api/tags | python3 -m json.tool | grep '"name"'
```

## Chat (Open WebUI)

`https://__HOST__:8444/` is the friendly front end for the same server: model
picker top-left, documents, chat history per account. Admin creates accounts.

## Your editor

Any Ollama-compatible extension (Continue, Cody, the JetBrains AI plugin's
local provider…) works over the SSH tunnel above with base URL
`http://localhost:11434`. Over VS Code Remote-SSH the extension runs on the DGX
already and can use `http://172.17.0.1:11434` directly.

## From Python

```python
import os, requests
r = requests.post(f"{os.environ['OLLAMA_HOST']}/api/generate",
                  json={"model": "qwen3.5:35b", "prompt": "One sentence on DGX Spark.", "stream": False})
print(r.json()["response"])
```

## Pulling a new model

Model files are shared (`/usr/share/ollama`), so pulling is an admin action —
ask, with the exact tag. A pull of a large model takes the GPU memory of
whoever is using it at that moment only when it loads, not while downloading.
