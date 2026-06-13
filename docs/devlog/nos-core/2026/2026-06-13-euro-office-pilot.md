---
id: 2026-06-13-euro-office-pilot
title: "Euro-office pilot — the sovereign OnlyOffice fork, one variable away"
date: 2026-06-13
namespace: nos-core
summary: "Euro-office — the OnlyOffice fork backed by Nextcloud, IONOS, Proton, XWiki and OpenProject — turned out to be a JWT-compatible, multi-arch drop-in for our document server. nOS now pilots it behind a single image variable; the role rename waits for the first stable release. One premise correction: euro-office is an editing engine only, so Documenso (e-signing) stays."
tags: [euro-office, onlyoffice, sovereignty, pilot]
actors: [pazny, claude]
related: [roles/pazny.onlyoffice/defaults/main.yml]
---
nOS is built on a simple bet: every service FOSS, every byte local, and —
where possible — European. So when a consortium of Nextcloud, IONOS, Proton,
XWiki, OpenProject and friends forked OnlyOffice into
[euro-office](https://github.com/euro-office), it went straight onto the
exploration list as a candidate to replace both ONLYOFFICE and Documenso.

## What the research actually found

Half the premise survived contact with the repository:

- **It IS a serious OnlyOffice DocumentServer fork** (AGPLv3, 22 repos,
  version 9.3.1 released 2026-06-09, first stable announced for summer 2026).
  The fork rationale is exactly the kind nOS cares about: upstream
  "typically does not review or accept pull requests," build instructions
  were unreliable, and the development team's jurisdiction made
  collaboration hard.
- **It is NOT a Documenso replacement.** Euro-office is a collaborative
  *editing engine* meant to be embedded in host platforms — there is no
  e-signing surface at all. Documenso stays.

## The drop-in test

Three facts make the pilot almost embarrassingly cheap:

1. `ghcr.io/euro-office/documentserver` publishes **multi-arch manifests** —
   `docker manifest inspect` shows a real `arm64` layer, which is the
   non-negotiable gate on an Apple Silicon home lab.
2. The container speaks the **same `JWT_SECRET` contract** as
   `onlyoffice/documentserver`, so the existing Nextcloud / BookStack /
   Outline embed wiring (shared `onlyoffice_jwt_secret`) carries over
   unchanged.
3. The fork is young enough that one rough edge surfaced immediately: the
   9.3.1 "release" exists only as a *source* release — ghcr carries no
   semver image tags yet, just `latest`/`main`/`develop` and CI branch
   builds (the first pilot converge failed on exactly that, `9.3.1: not
   found`). Preview status, confirmed the hard way.

So the structural change is one variable: the role's compose template now
renders `{{ onlyoffice_image }}:{{ onlyoffice_version }}`, defaulting to the
original image. The pilot flip lives in the operator's `config.yml`:

```yaml
onlyoffice_image: "ghcr.io/euro-office/documentserver"
onlyoffice_version: "latest"   # no semver image tags yet — re-pin at stable
```

Revert = delete two lines and re-run `--tags onlyoffice`. The full role
rename (`pazny.onlyoffice` → `pazny.eurooffice`, plugin manifest, manifest
row, registry) deliberately waits for the first stable release — preview
builds don't get to own a role name.

## The migration trap the pilot earned

The first live switch died twice, and both failures are worth their tuition:

1. **The internal-PG bind mount carries the old image's identity.** The role
   bind-mounts `/var/lib/postgresql`, and the existing cluster was
   provisioned by OnlyOffice with a `onlyoffice` DB user — euro-office
   authenticates as `eurooffice`, so docservice hung and the healthcheck
   502'd while supervisor cheerfully reported everything RUNNING.
2. **Euro-office's entrypoint cannot initdb an empty directory** — the
   cluster is baked into the image layers, so an empty bind mount just
   shadows it and PostgreSQL restart-loops on a missing `16/main`.

The fix (now documented step-by-step in the role defaults): move the old DB
dir aside as a dated backup, seed the bind from the image's baked cluster
with a one-off `cp -a`, start. The internal PG holds only transient
document-server state — documents live in the host applications — so the
reseed is safe.

After that: container **healthy**, `/healthcheck` 200, and a real JWT-signed
`ConvertService.ashx` round-trip produced a PDF (`endConvert: true`) on
ARM64. The editing engine works; the browser-level Nextcloud embed is the
remaining operator smoke test.

## What pins it

`test_wordpress_rbac_mirror.py::test_onlyoffice_image_is_flippable_var`
asserts the template stays variable-driven and the flip instructions stay in
the role defaults, so a future "cleanup" can't quietly hard-code the image
back.
