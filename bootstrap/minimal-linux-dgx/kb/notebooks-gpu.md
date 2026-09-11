---
title: Notebooks and the GPU
section: dev
order: 3
summary: JupyterHub gives you a Lab as your own user; the shared kernel has CUDA torch; add your own kernels.
---

`https://__HOST__:8445/` — log in with your Linux credentials. The Hub starts a
JupyterLab **as you**, in your home directory, and stops it when idle. A Hub
restart by the admin does not kill running notebooks.

## The shared kernel: `Python 3 (ipykernel)`

Comes from `/opt/nos-dgx/jupyterhub/venv` (read-only, admin-managed) and
carries `torch` built for CUDA 13 on this GPU, plus pandas, matplotlib,
requests, pyyaml. A first cell worth running:

```python
import os, torch, requests
print(torch.__version__, torch.cuda.get_device_name(0))
x = torch.randn(4096, 4096, device="cuda"); print(float((x @ x).sum()))
r = requests.get(f"{os.environ['KEAP_API_URL']}/agent/v1/tables/roadmap/rows",
                 headers={"Authorization": f"Bearer {os.environ['KEAP_AGENT_TOKEN_RO']}"})
print(r.status_code, len(r.json()["data"]["rows"]), "roadmap rows")
```

The KEAP token in the environment is the one your group may hold (read-only for
`nos-users`, read-write for maintainers); `OLLAMA_HOST` points at the local
model server too.

## Your own kernel (your packages)

The shared venv is read-only. For your own dependencies make a venv and
register it as a kernel — it appears in the launcher next to the shared one:

```
python3 -m venv ~/venvs/proj
~/venvs/proj/bin/pip install ipykernel <your packages>
~/venvs/proj/bin/python -m ipykernel install --user --name proj --display-name "Python (proj)"
```

For a CUDA-capable torch in your own venv:
`pip install torch --index-url https://download.pytorch.org/whl/cu130`
(aarch64 wheel, a few GB).

## Sharing the GPU

There is one GPU and 121 GB of memory shared with Ollama. A loaded 120B model
takes most of it; `nvidia-smi` shows who holds what. Free your kernel's memory
when done (*Kernel → Shut Down*), and expect Ollama to unload an idle model
after 30 minutes.

## Terminals

*File → New → Terminal* is a real shell as you — `docker`, `nos dtt`, git all
work there exactly as over SSH.
