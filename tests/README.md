# tests/

`tests/anatomy` is the offline suite. The boundary in
`tests/anatomy/_live_guard.py` hides `~/.nos`, refuses docker, scrubs secret
environment variables, and blocks loopback service ports.

A test marked `@pytest.mark.live` is skipped unless the run opts in. After a
converge, the live lane is:

```bash
NOS_LIVE=1 python3 -m pytest tests/anatomy -m live
```

The default run stays offline:

```bash
python3 -m pytest tests/anatomy -q
```
