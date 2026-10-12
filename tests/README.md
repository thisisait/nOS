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

A test marked `@pytest.mark.docker_cli` is the narrow exception. It may run
`docker compose -f <file> config` (local flags only) against the real Docker
CLI, and every other docker invocation is still refused. The command renders
synthetic compose files and does not contact the daemon; the secret store,
secret environment variables, and loopback ports stay closed. Use it for a
parse of files the test itself wrote. A probe of a container or of the estate
stays `@pytest.mark.live`.
