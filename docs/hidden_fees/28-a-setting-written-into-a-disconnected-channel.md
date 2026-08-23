# 28 — A setting written into a channel nothing was reading

**Found 2026-08-23, by a reader disagreeing with a line that had just been fixed.**

One line of HedgeDoc's compose template. Three states, spread over ten weeks,
each one arrived at confidently and each one wrong at a different layer:

| | the line said | why it was wrong | how long |
| --- | --- | --- | --- |
| 2026-06-14 | `sslmode=require` | read a role default from another role's scope — never rendered | 9 weeks |
| 2026-08-23 | `sslmode=no-verify` | rendered, resolved, and then **discarded before the driver** | 8 hours |
| 2026-08-23 | *(no sslmode at all)* | the URL cannot express the setting; a file can | — |

The second is the one worth the entry. The first is
[23](23-a-pin-that-never-rendered.md) — a template that says one thing and a
render that says another — and it was fixed properly, with a gate, and the
value in the container's environment was afterwards **exactly right**.

`pg_stat_ssl` still reported the backend `ssl=f`. One plaintext backend of
forty.

## The mechanism, which is not a subtlety

Between the URL and the driver sits an ORM, and it has an allow-list
(`sequelize/lib/dialects/postgres/connection-manager.js:96`):

```js
_.merge(connectionConfig, _.pick(config.dialectOptions, [
  'application_name', 'ssl', 'client_encoding', /* … */
]))
```

`sslmode` is not on it. The parameter was well-formed, correctly spelled, and
silently **picked out**. Nothing was misconfigured, misparsed, or malformed —
there was simply nobody at the other end of the wire.

And `ssl`, which *is* on the list, must be an object, because pg does
`Object.assign(options, this.ssl)` for anything that is not literally `true`.
A query string cannot carry an object. **The setting was not expressible in
that channel at any spelling** — so no amount of care about the *value* could
ever have worked.

## Why it survived a correction

Because the correction was reasoned at the wrong layer, and reasoned well.
Fixing state 1 meant establishing HedgeDoc's driver family — Sequelize over
node-postgres — and choosing the spelling that family requires. That reasoning
is correct and it is in
[`doctrine/foreign-properties.md`](../doctrine/foreign-properties.md) §5. It
just answers a question nobody was going to ask.

The template even said so, in the comment written beside the fix:

> HONEST LIMIT: Sequelize may ignore an `sslmode` query param entirely, in
> which case this is inert. It cannot break, and `tools/tls-uptake.py` says
> which happened.

**That is the fee.** The doubt was recorded, correctly, in the right place — and
then the line shipped anyway, because an inert setting "cannot break". It cannot
break, and it *can* read as a control to every future reader, which is the more
expensive of the two. Two greps in `node_modules` stood between the doubt and
the answer, and the run to write them was never made.

## What closes it

- The URL is **clean**. Where a channel cannot carry a setting, it must not
  appear to — `test_postgresql_ssl.py::OUT_OF_BAND` requires the absence and
  fails on a re-added `?sslmode=` or a stringy `?ssl=`.
- The control moved to where the application actually reads it: a mounted
  `config.json` (`db.dialectOptions.ssl`), gated on the same variable as the
  mount, rendered on both `NODE_ENV` keys because a wrongly-keyed file is read
  and ignored in silence.
- The whole derivation — merge order, allow-list, why an object and not a
  string — lives in that file's header, cited from the compose template.
  Doctrine: `foreign-properties.md` §5.2.

## The rule this generalises to

**A doubt about whether a channel is connected is not closed by noting the
doubt.** It is closed by reading the consumer, or by measuring the effect.
Both were available and cheap here.

And the second-order one, which is why this is a fee and not a bug: **a
correction can be right about everything it examined and still land on an inert
line.** The estate's habit of gating each fix caught the layer that failed
last time and had nothing to say about the next one down. The only check that
spans every layer is the one that reads the *effect* — `tools/tls-uptake.py`,
which had already been built for exactly this and which said `ssl=f` the whole
time.

## What is still owed

- **Only one channel was audited.** Every other service configuring a driver
  through a URL query has the same question open and it has not been asked:
  what does the layer in between *pick*? Miniflux, paperclip and grafana pass
  their DSN to libpq-family drivers with no ORM in the path, which is why they
  measured encrypted — but that is an observation, not an audit.
- **Nothing proves the mount survives an image bump.** HedgeDoc could move
  `config.json`'s path or its merge order; the gate reads our template, and
  only `tls-uptake.py` would notice. That is the correct division of labour and
  it means the reader must keep being run.
