# vLLM

> One resident model, batched across concurrent users, behind an OpenAI-compatible
> API on an NVIDIA GPU host. Beside Ollama, not instead of it: Ollama keeps serving
> every other model on demand; vLLM holds the one many people use at once.

## Quick Reference

| | |
|---|---|
| **Toggle** | `install_vllm: false` (Linux + NVIDIA GPU visible to Docker via CDI) |
| **Role** | `roles/pazny.vllm` — compose service `vllm` in the `iiab` stack |
| **Image** | `vllm_image` (NGC `nvcr.io/nvidia/vllm`, tag **and** digest) |
| **Model** | `vllm_model` @ `vllm_model_revision` (a pinned Hugging Face snapshot), served as `vllm_served_model_name` |
| **API** | `http://127.0.0.1:{{ vllm_port }}/v1` (host), `http://vllm:8000/v1` (shared_net); key `vllm_api_key` |
| **Backend row** | `vllm` in `state/habitat/llm-backends.yml` (local, EU) |
| **Memory** | `vllm_gpu_memory_utilization` — pre-allocated at start, from the same pool as Ollama, notebooks and containers on unified-memory hosts |

## How the weights arrive

A multi-GB download must not hold a converge, and the stack's strict health-wait
cannot wait for one. The role asks a reader whether the pinned snapshot is complete;
if not, a detached one-shot container of the same image fetches it and the converge
renders **no** vllm service (it says so). The next converge that finds the snapshot
whole renders the service, which then starts with `HF_HUB_OFFLINE=1` against exactly
that revision.

## Measured (spark1, DGX Spark GB10, 2026-10-19)

Ollama `qwen3.5:35b` (Q4_K_M), 400-token answers: 65 tok/s aggregate at 1, 4 and 8
concurrent streams — it serialises; at 8 streams the median first token waits 18.7 s.
vLLM numbers are added when the PoC run lands.
