"""Candidate orchestration-host adapters for tools/orchestrator-acceptance.py.

The harness imports candidates lazily (`from orchestrator_hosts.langgraph_host
import LangGraphHost`). Python puts the script's own directory — tools/ — at
the front of sys.path, so `python3 tools/orchestrator-acceptance.py` from the
repo root resolves this package with no sys.path plumbing in the harness.

A candidate whose library is missing must report a one-line skip reason from
`available()` and never raise at import time — the harness runs on boxes
without any candidate installed. The LangGraph candidate's library lives in
the isolated `.spike-venv/` (docs/idea/17 clause 2), so the full run is:

    .spike-venv/bin/python tools/orchestrator-acceptance.py --host langgraph

Plain `python3` still works and reports the skip.
"""
