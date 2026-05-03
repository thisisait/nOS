"""Pulse runners — invoke registered jobs.

A4 PoC: only :mod:`pulse.runners.subprocess` (non-agentic shell/python jobs).

A8 will add :mod:`pulse.runners.agent` (claude SDK invocations) using the
same job dispatch shape — a job's ``runner`` field selects which.
"""
