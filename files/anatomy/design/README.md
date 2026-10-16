# design tokens (vendored from thisisait/design)

`tokens.json` is the single source of the AIT design system
(https://github.com/thisisait/design, `tokens/tokens.json`), last synced at commit `5811dc3`.
It is vendored because the estate runs offline and a converge must not fetch.

Consumers in this repo:

- `tools/cc/theme.py` — the nos-cc Textual theme, GENERATED from the `glass-face` theme
  here by `tools/design-sync.py`; gate `tests/anatomy/test_cc_theme_is_design_tokens.py`.
- not the face organ yet: `files/anatomy/face` has diverged from thisisait/nos-face (own
  `--bg/--fg/--glass` tokens); nos-face maps onto these tokens, this tree does not.

Not yet consumers: Wing (`files/anatomy/wing/www/assets/tokens.css`, its own GitHub-dark
scale, gated by `tests/anatomy/test_wing_ui_tokens.py`) and apex (`ait.css`, the brand
source the design system was derived from). Reference for agents: `docs/design-system.md`.

Sync: `python3 tools/design-sync.py ../design`.
