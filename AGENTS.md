# AGENTS.md — Stick Arena: Ballistick 558 reference workspace

## 1. Scope

This repository is a **source-and-reference workspace for Stick Arena: Ballistick
558 only**. The single client target is:

```
htdocs/stickarena/sab558.swf   sha256 f86d224501c202fb11c6c681c1ebdd6c2009b27f0a4a645351ad42ebeda3302a
```

Everything we document, extract, compare or explain must be traceable to that
file, to the server in `ballistickemu/`, to the web endpoints in
`htdocs/stickarena/*.php`, or to the schema in `Import database/`.

### 1.1 Hard exclusions

Do **not** use any of the following as a reference, comparison, source of assets,
or behavioural evidence:

| file | why excluded |
| --- | --- |
| `htdocs/stickarena/sab588.swf` | Ballistick 588 — different build |
| `htdocs/stickarena/dimensions.swf` | Stick Arena Dimensions — different game |
| `htdocs/stickarena/settings588b.ini`, `settings598b.ini` | 588 / 598 client config |
| `htdocs/stickarena/upgradevalues588.ini`, `upgradevalues598.ini` | 588 / 598 shop tables |
| `htdocs/stickarena/maps/563/**`, `maps/593/**` | map sets for other client builds |

They stay in the tree because the upstream repository ships them and this
workspace must not delete upstream files. They are recorded as `other-version`
in `reference/sab558/analysis/repo_inventory.json` and nothing else.

If a question can only be answered by looking at 588 or Dimensions, the answer is
"not determinable from 558 material". Say that instead of guessing.

## 2. Source preservation

The original client, server and data files are **read-only inputs**.

- Never edit, reformat, re-save, decompile-in-place or re-compress anything under
  `htdocs/`, `ballistickemu/` or `Import database/`.
- The extraction pipeline opens the SWF read-only and verifies its SHA-256 before
  and after every run. A changed hash is a fatal error, not a warning.
- Never rewrite a SWF with the decompiler. If an experiment needs a modified
  client, copy it into a scratch directory outside the tracked tree and say so.
- Never run `git clean`, `git reset --hard`, or delete upstream files to "tidy"
  the repository.
- Do not add, remove or upgrade dependencies (Maven, PHP, Python packages, the
  decompiler) without explicit permission. The pipeline is deliberately
  stdlib-Python plus an already-installed JPEXS binary.

## 3. Generated output lives in exactly one place

```
reference/sab558/
  source/      identity record of the original SWF (hash, size, capture time)
  scripts/     the reproducible tooling (bash + stdlib Python)
  extracted/   all decompiled assets (git-ignored; regenerate with the pipeline)
  manifests/   machine-readable JSON/CSV indexes and verification results
  analysis/    generated inventories, string dumps and the extraction report
  docs/        hand-written architecture / workspace documentation
  logs/        per-stage decompiler logs (git-ignored)
```

Rules:

- Nothing generated is written outside `reference/sab558/`.
- `extracted/` and `logs/` are derived and git-ignored; `manifests/`,
  `analysis/`, `docs/` and `scripts/` are the reviewable deliverables.
- Never hand-edit a file in `extracted/`. If the extraction is wrong, fix the
  pipeline and re-run it.
- Never hand-edit a file in `manifests/`; they are outputs of
  `swf_inspect.py` / `link_exports.py` / `verify_extraction.py`.

## 4. Documentation standards

Every factual claim in `docs/` must be one of:

1. **Confirmed** — observed directly in 558 material, with a pointer:
   - a tag/character id and byte offset (`manifests/tags.json`),
   - an AVM1 string literal and its location (`manifests/as2_strings.json`),
   - a source location (`file.java:line`),
   - a database table/column (`Import database/ballistick_struct.sql`).
2. **Assumption** — plausible but unverified. Must be labelled
   `Assumption:` and must say what evidence would confirm it.

Never present an assumption as a finding. Never describe behaviour that is not
present in the 558 client or the server code. When the client's intent is
ambiguous, quote the decompiled ActionScript or the packet handler and let the
reader judge.

Style:

- Refer to characters by their **original SWF id** (`DefineSprite_237`,
  `DefineShape_233`), never by a renamed/renumbered id.
- Refer to frames with the original numbering (`main_timeline/frame_5`,
  `DefineSprite_237/frame_2`).
- Preserve the client's own terminology (`spinner`, `lab pass`, `cred ticket`,
  `map cycle`, `quickstart`) instead of inventing synonyms.
- Keep confirmed findings, assumptions and open questions in separate sections.

## 5. Reproducibility

Any statement about extracted assets must be reproducible from:

```
reference/sab558/scripts/extract_sab558.sh
```

The pipeline must stay:

- **idempotent** — re-running reuses complete stages, `--force` redoes them;
- **stage-isolated** — one decompiler invocation per asset class, each with its
  own log and recorded exit code;
- **verifiable** — `verify_extraction.py` re-hashes every extracted file and
  fails loudly on a missing/incomplete artefact.

Do not replace a pipeline step with a manual GUI extraction. If JPEXS cannot do
something non-interactively, record it as a limitation in
`analysis/extraction_report.md` and in `docs/`.

## 6. Definition of done

A change to this workspace is done when:

- `reference/sab558/scripts/extract_sab558.sh --verify-only` passes, and
- `analysis/extraction_report.md` reflects the current state, and
- `git diff --stat` shows only intended changes, and
- any limitation you introduced is written down where a reader will find it.

If you could not verify something, say so explicitly rather than implying it
worked.
