# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Maintaining this file
- When a change alters a documented invariant, a default, a public API signature, or introduces a non-obvious
  gotcha, update the relevant section here as part of the same phase, before reporting the phase complete. Do not
  log what changed; record only what a future session needs to know to avoid getting it wrong.

## Instructions
- Read a file in this session before any Edit or Write to it. Never attempt an edit on a file you have not read.
- Do not fill gaps from adjacent knowledge. If you don't know whether tool X does Y, say so.
- Before naming any API, method, default, or cardinality, read it from the installed package or the repo. If you
  can't, label it unverified.

## Project Overview

crfutils is a Python package for working with CDISC ODM v2.0 CRFs (blank and annotated CRFs described as ODM v2.0
metadata). It is the sister project of defineutils (`/home/sam/src/defineutils`) and keeps its shape. The design
is `CRF_UTILS_PLAN.md`. Seven modules:
- **validate**: schema validates an ODM v2.0 file against the bundled XSD (`crfvalidate`)
- **crfhtml**: renders the CRFs as HTML with the bundled stylesheet (`crfhtml`)
- **crfpp**: pretty-prints an ODM v2.0 file (`crfpp`)
- **crfrefs**: OID reference/definition integrity plus CRF-structure checks (`crfrefs`)
- **metrics**: element counts and CRF/annotation/visit metrics (`crfmetrics`)
- **crfreview**: renders with crfhtml and opens the browser; the Windows double-click target (`crfreview`)
- **crfpdf**: the annotated CRF PDF and the page-references JSON (`crfpdf`; optional `[pdf]` dependencies)

Scope is **ODM v2.0 metadata only**. ClinicalData, ReferenceData and Association are never examined; crfrefs and
crfmetrics print a NOTE when a file has them. Only the first Study/MetaDataVersion is rendered and measured.

## Commands

```bash
pip install -e /home/sam/src/odmlib    # until the odmlib release with the ODM v2.0 fixes is on PyPI
pip install -e ".[pdf,test]"           # re-run after the version, [project.scripts] or [project.gui-scripts] change
pytest                                 # PDF tests skip only when WeasyPrint/Pango is missing
CRFUTILS_BIN=.venv/bin pytest          # also runs tests/test_commands_match_modules.py against the installed commands
CRFUTILS_UPDATE_GOLDEN=1 pytest tests/test_crfrefs.py   # regenerate tests/data/golden/*.json after a deliberate change
pytest --cov=crfutils                   # the README coverage badge is static: update it when this figure moves
pytest tests/test_crfhtml.py::test_toc_and_matrix       # one test
```

The version lives in three places that tests keep equal: `pyproject.toml`, `crfutils/__init__.py` and the static
version badge at the top of `README.md` (`tests/test_entry_points.py`). The coverage badge is static too and not tested.

Each command is `python -m crfutils.<module>` (crfvalidate is `crfutils.validate`, crfmetrics is `crfutils.metrics`).
The input flag is `-c/--crf` everywhere except crfreview (positional). Every parser sets `prog=` and `--version`.

## Architecture

```
crfutils/
  _common.py      run(main), write_text/write_bytes, require_file, check_destination, display_path
  _odm.py         ODM_NS, ODM_SCHEMA, parse_odm (lxml), check_odm_v2 (the version gate), design_from_lxml
  _model.py       odmlib loading (load_crf, permissive_would_load, load_error_message, load_context),
                  clinical_data_note, design_from_model
  _design.py      DesignData (plain data) and StudyDesign (forms, visits, schedule, walk, annotations); no lxml/odmlib
  annotations.py  the SDTM annotation grammar (parse, target_key); pure Python, never raises
  validate/ crfhtml/ crfpp/ crfrefs/ metrics/ crfreview/ crfpdf/   one package per command
```

Each command package: a main class caching its result on `self._result`; `*_to_string / _to_file / _to_console /
_to_json`; a `report.py` that imports nothing from the main module (duck-typed result); `__main__.py` with `main()`
returning the exit code and `run()` = `_common.run(main)`. Package data is found through `Path(__file__).parent`.

### CLI invariants
- Entry points target `run()`, never `main()`; `run()` is `_common.run(main)`, which exits 130 on Ctrl-C and 0 on
  BrokenPipeError via `_common._quiet_exit` (os._exit; tests patch it). crfreview keeps its own `run()`.
- `main()` of the report commands re-raises `BrokenPipeError` ahead of `except Exception`.
- Exit codes: 0 done; 1 the file is invalid (crfvalidate) or has errors (crfrefs), or an unexpected traceback;
  2 could not run (missing/unparseable input, not ODM v2.0, unwritable output, WeasyPrint missing). crfpp exits 2 on
  `CrfPrettyPrintError` (unlike definepp).
- Messages that tell the user to run another tool say `crfvalidate -c <file>`, never `python -m`.
- Every file is written through `_common.write_text`/`write_bytes`, whose PermissionError handler checks
  `os.path.isdir()` so a folder is reported as a folder on Windows; `tests/test_write_to_folder.py` patches
  `crfutils._common.open`. crfhtml/crfpdf call `_common.check_destination` before transforming.
- CLI tests start processes only through `run_cli`/`cli_command` in `tests/conftest.py` (`CRFUTILS_BIN`); the one
  exception is `run_module`, the `python -m` reference.

### The version gate (`_odm.check_odm_v2`)
The root must be `{http://www.cdisc.org/ns/odm/v2.0}ODM`; `@ODMVersion` is optional (8 of 21 CDISC examples omit
it; Columbia does) but must match the XSD pattern when present. It works on an lxml or an ElementTree root.
crfhtml/crfpdf apply it to the lxml tree; crfrefs/crfmetrics apply it to the ElementTree root
`loader.open_odm_document()` returns, **before** `loader.root()` builds the model, so an ODM 1.3.2 file gets a clear
refusal rather than an odmlib type error. crfvalidate and crfpp do not gate.

### Study design (`_design.py`)
`StudyDesign` is the single implementation of form order, visit order, the row walk and the annotation records.
Two extractors fill its `DesignData`: `_odm.design_from_lxml` and `_model.design_from_model`;
`tests/test_design.py::test_lxml_and_odmlib_read_the_same_design` asserts they are equal on every fixture. Keep
them equal: a field added to one must be added to the other.
- Children sort by `OrderNumber` with `sort_key`: **children without one come first**, then document order. That is
  exactly what the stylesheet's `<xsl:sort data-type="number"/>` does (NaN sorts first, XSLT sorts stably); verified
  against libxslt.
- `walk(form)` yields a `Node` per nested-group heading and per item occurrence, in the order the stylesheet
  renders rows; a cycle (a group already on the path) or nesting deeper than `MAX_DEPTH` (10) gets its heading row
  but is not entered, and is recorded in `cycles`/`too_deep`. The stylesheet does the same (`cycle`/`too-deep`
  marker rows). `tests/test_crfhtml.py` asserts row count == walk length on every fixture.
- Visit order: Protocol/StudyEventGroupRef, expanded recursively through StudyEventGroupDef, then unreached groups
  and events in document order. Form order: first appearance in the schedule, then unscheduled forms in document
  order; document order when there is no schedule.
- Group annotations by level: Form `formAnnotation`|`SDTM` aliases else `@Domain`; Section
  `formSectionAnnotation`|`SDTM` else `@Domain`; Concept `SDTM` only. `annotations()` yields the same records, with
  the same fields, that the HTML carries in `data-*`; `tests/test_annotations_agree.py` compares them in both modes.
- `known_domains` = domains named by group annotations, qualified datasets and `SUPPxx` (minus the SUPP prefix);
  it drives the bare-domain-vs-variable decision and the prefix rule.

### The annotation grammar (`annotations.py`)
`parse(text, level, source, context_domain, known_domains)` never raises. `attr:Domain` text is a domain only when
it matches `[A-Z][A-Z0-9]{1,7}` (Result_ODMv2 has `Domain="all"`, which is reported unparsed). Dataset resolution
order: qualified, supp, prefix (longest known domain that is a strict prefix), context; else `dataset_unresolved`.
`target_key()` is a **public contract** with the page-refs JSON (`DATASET.VARIABLE[ where VAR = VALUE[ and ...]]`,
conditions sorted by variable, IN values sorted); change it only with a `pagerefs.SCHEMA_VERSION` bump.

### crfhtml
- `STYLESHEET` compiles once; serialize the result only with `str()`/`bytes()`, **never `etree.tostring()`**
  (it writes XML and self-closes empty elements).
- The stylesheet is **XSLT 1.0** and `tests/test_crfhtml_stylesheet.py` fails on 2.0 constructs; **log every edit in
  `stylesheet_changes.md`**. `xsl:key`s are anchored at `/odm:ODM/odm:Study[1]/odm:MetaDataVersion[1]`.
- Integer params are validated and passed as `"0"`/`"1"`; string params go only through `etree.XSLT.strparam()`.
  `formOrder`/`visitOrder` are `' OID1 OID2 '`; an OID with whitespace falls back to document order with a note
  (`CrfHtml.notes`, printed by the CLI).
- **Python owns all ids.** The stylesheet emits only `data-*` (a test enforces no `id` attributes in it).
  `_assign_ids` sets `F.<sanitized OID>` (collisions get `-2`, `-3`), the TOC/matrix `href`s and `A.<n>` on every
  `span.anno` in document order. `data-group-path` joins OIDs with `" > "` (OIDs may contain `/`).
- The HTML contract with crfpdf (elements, classes, `data-*`) is in CRF_UTILS_PLAN.md section 5. Refusals: not
  ODM v2.0, no `ItemGroupDef[@Type='Form']`, output == input, output is a folder.
- Print mode (`mode="print"`): no `<style>`, static controls, every codelist item listed with a `.box`, codelist
  item annotations beside the option (on screen they are in the annotation column); a title page with
  `title_page=True`; a footer only when `generated_on` is given (keeps screen output deterministic).

### crfreview
A port of defineview: HTML beside the CRF (falls back to `<tempdir>/crfutils/<sha256 of path>[:12]/` on
`CrfHtmlWriteError`), `--temp`, `-o`, `--no-open`; an error page in the temp folder (never beside the CRF); argparse
output and problems with no page go to `tell_user()` (stderr, or a MessageBoxW without a console). Never open an
`.xml` through the OS. No absolute-links logic: the HTML has only `#fragment` links.

### crfrefs and crfmetrics (odmlib)
- Both load through `_model.load_crf` (odmlib `XMLODMLoader(model_package="odm_2_0", ns_uri=ODM_NS)`), walk
  `elem.__dict__` (so an unset attribute on a permissive load is simply absent), and run load + traversal inside
  `_model.load_context(permissive)`. The load-failure message names `crfvalidate` and adds the `--permissive` hint
  only when `permissive_would_load()` succeeds.
- **odmlib is the mapping authority.** `create_oid_checker("odm_2_0")` supplies `ref_def`, `ref_def_any_of` (the
  workflow/timing references that may point at several classes) and `skip_attr` (`FileOID`, `PriorFileOID`). crfutils
  adds no supplements: a gap is fixed in odmlib (the fixes are listed in CRF_UTILS_PLAN.md section 4A).
  `tests/test_crfrefs.py::test_every_xsd_reference_attribute_is_checked_skipped_or_unchecked` walks the XSD from
  Study and fails if an `oidref`/`IDREF` attribute is neither mapped, skipped, nor on an unchecked element.
- crfrefs scopes definitions and references to their MetaDataVersion (the XSD's uniqueness is per MDV; files with
  several versions reuse OIDs). A reference resolves in its own MDV, then globally (Study, AdminData); one defined
  only in another MDV says so. `Include` references are counted, not resolved. Orphan-exempt: `ODM` (odmlib's
  `skip_elem`), `Study`, `MetaDataVersion`, Form ItemGroupDefs. The CRF-structure checks run on the first MDV's
  `StudyDesign`.
- crfmetrics' inventory is a BFS over `odmlib.odm_2_0.model` from `ODM`, resolving children by name; it gives 124
  element types (pinned) in sections document / definitions / nested / admin (everything first reached under
  AdminData). A test checks every XSD element reachable from Study is in it. Counts are per class name across the
  whole loaded document (ClinicalData is not modelled by odmlib, so it never appears).
- The `odmlib` pin in `pyproject.toml` is `>= 0.2.1` because the editable install of the fixed odmlib still reports
  0.2.1; raise it to the release that ships the fixes. `tests/test_model.py` fails on an odmlib without them.

### crfpdf
- WeasyPrint and pypdf are imported only in `_import_engines()` inside `render()`; ImportError **or OSError** (a
  missing Pango) becomes `CrfPdfError` with `INSTALL_HELP` (exit 2). The other commands never import them
  (`tests/test_crfpdf_unavailable.py`).
- Pipeline: `CrfHtml(mode="print", title_page=True)` -> parse every `span.anno` (`data-domain-index` 1-4 by first
  appearance of the domain on the form, 0 unresolved) -> inject `@page size`, `@font-face` (bundled Liberation Sans
  as "CRFUtils Sans", `file:` URIs) and `acrf.css` -> `weasyprint.HTML(string=...).render()` -> `page_of` from
  `page.anchors` (first page an id appears on) -> form ranges (first page to the next form's first page - 1; the
  last form runs to the end) -> **delete every non-`F.*` anchor** before `write_pdf()` so only forms are named
  destinations -> pypdf pass (outline: Table of Contents, Visit Matrix, Forms, Visits; `/UseOutlines`;
  `DisplayDocTitle`; `%PDF-1.7`).
- `@page` rules set `font-family` too: margin boxes do not inherit from body and would embed a fallback font.
- Printed page numbers equal physical pages (one arabic sequence from the title page). `bookmark-level: none` on
  headings so CSS bookmarks don't duplicate the pypdf ones.
- Defaults: `<stem>_acrf.pdf` beside the input, `<pdf stem>.pagerefs.json` beside the PDF, `--html` only on request.
  `write()` checks every destination before rendering.
- `pagerefs.py` builds the JSON; its shape and `SCHEMA_VERSION` are a public contract (README has the consumer
  recipe). Annotations merge by (level, form, item, coded value, text).
- Measured: the 14-form/394-item `data-definition-engine/output/crf-2.0.xml` renders 103 pages in ~7 s and 350 MB.

### Tests
- Fixtures in `tests/data/` (provenance in `tests/data/README.md`); `crf_synthetic.xml` is authored and must stay
  XSD-valid and strictly loadable. Build broken files with the `edited_crf` fixture, never commit them.
- `tests/data/golden/` holds crfrefs JSON goldens (odmlib version masked); regenerate deliberately.
- The Columbia example has 12 genuine reference errors (dangling ConditionOIDs, a duplicate Transition OID) that
  `test_crfrefs.py` pins; they are in the CDISC file, not in crfutils.
- Tests that patch `sys.stdout`/`sys.stderr` (crfreview) must do it in the test body, after pytest's capture.
