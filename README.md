# crfutils

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Version 0.1.0](https://img.shields.io/badge/version-0.1.0-blue.svg)](pyproject.toml)
[![Status: under development](https://img.shields.io/badge/status-under%20development-orange.svg)](#development)
[![Coverage 91%](https://img.shields.io/badge/coverage-91%25-green.svg)](#development)

## CDISC ODM v2.0 CRF utilities

crfutils is the sister project of [defineutils](https://github.com/swhume/defineutils) for CDISC ODM v2.0 case
report forms (CRFs): blank or annotated CRFs described as ODM v2.0 metadata (Study, MetaDataVersion, ItemGroupDef
forms, sections and concepts, ItemDef, CodeList). It keeps defineutils' package shape, command-line conventions,
report formats and test harness. The package currently includes 7 modules:
1. `validate`: schema validates an ODM v2.0 file against the bundled ODM v2.0 schema
2. `crfhtml`: renders the CRFs in an ODM v2.0 file as HTML by applying the bundled stylesheet
3. `crfpp`: pretty-prints (re-indents) an ODM v2.0 file
4. `crfrefs`: checks the OID reference/definition integrity of an ODM v2.0 file
5. `metrics`: reports metrics for an ODM v2.0 CRF file
6. `crfreview`: renders a CRF with crfhtml and opens it in the default browser
7. `crfpdf`: writes a submission-ready annotated CRF PDF, with page breaks, a table of contents and bookmarks,
   plus a JSON file of the page each annotation lands on, for a Define-XML page-reference updater

The `crfhtml` module renders the forms of the first Study/MetaDataVersion with the bundled stylesheet (a reworked
copy of Lex Jansen's `odm_2-0_transform.xsl`, MIT). A form is one table: a heading row per nested section or
concept and a row per item, with the question, a response control and the SDTM annotations. The forms are ordered
by the visit schedule when the file has one, and a table of contents and a visit matrix are added. A file in
another ODM version, or one that is not well-formed, is refused with an error that recommends running crfvalidate,
rather than rendered with content silently missing. Options turn the annotations off (a blank CRF), show each
item's DataType and Length, and omit the table of contents or the visit matrix.

The `validate` module schema validates an ODM v2.0 file and reports every schema validation error it finds, not
just the first one. Errors that say the same thing about the same kind of element are grouped into one finding
that lists each place it occurs, with a line number. The bundled ODM v2.0 schema is the default, but any schema
file can be used instead (`-s`, or the `xsd_file` argument in code).

The `crfpp` module pretty-prints an ODM v2.0 file. The reformat is byte-preserving apart from whitespace:
comments, processing instructions, element/attribute order, namespaces and the xhtml markup inside TranslatedText
are all retained.

The `crfrefs` module checks the OID reference/definition integrity of an ODM v2.0 file: references to OIDs nothing
defines, references that resolve to the wrong kind of element, duplicate OIDs within a MetaDataVersion,
definitions nothing references, and the structure of the CRFs themselves -- an ItemGroupRef chain that returns to
an ancestor, a form nested in another group, a visit that collects something other than a form, a concept that
contains a section, a form no visit collects, a visit with no forms. odmlib's ODM v2.0 model is the authority on
which attributes reference which definitions. ODM v2.0 metadata only: ClinicalData, ReferenceData and Association
are noted but not examined.

The `metrics` module reports what is in an ODM v2.0 CRF file: its size and creation date, the study and metadata
version, the CRF structure (forms, sections, concepts, items, code lists, visits and the visit matrix), the SDTM
annotations (how many items are annotated, by level, how many parsed, which datasets they reference), a per-form
table, and a count of every element type the ODM v2.0 model can hold -- an element the file does not use is
reported as 0 instead of being left out.

The `crfreview` module shows a CRF in the browser: it writes the HTML beside the ODM file and opens it in the
default browser, or opens a page saying why the file could not be shown. On Windows, choosing crfreview once to
open `.xml` files lets a double-click on a CRF show it in the browser.

The `crfpdf` module renders the annotated CRF as a PDF that meets what a submission's annotated CRF needs: a
title page, a table of contents with page numbers, the visit matrix, one page-broken section per form with a
repeating table heading, every codelist option listed, the annotations coloured by domain, running headers and
footers with "Page X of Y", bookmarks by form and by visit that open with the document, a named destination per
form, embedded fonts and no encryption. Beside the PDF it writes `<pdf>.pagerefs.json`: the physical page of
every annotation, indexed by `DATASET.VARIABLE[ where ...]`, which a Define-XML tool can turn into
`def:PDFPageRef` page references. It needs the optional `[pdf]` dependencies (WeasyPrint and pypdf).

## Installing crfutils

crfutils needs Python 3.10 or later. Install it from a clone of this repository (it is not on PyPI yet):

```commandline
pip install .
# with the PDF dependencies
pip install ".[pdf]"
# or, to have the commands on your PATH without a virtual environment
uv tool install .
```

Until the odmlib release carrying the ODM v2.0 fixes crfrefs and crfmetrics need is on PyPI (see
`pyproject.toml`), install odmlib from its repository first:

```commandline
pip install -e /path/to/odmlib
```

### The PDF dependencies

crfpdf renders with [WeasyPrint](https://weasyprint.org/), which needs the Pango system libraries:
- **Linux:** usually present; otherwise `apt install libpango-1.0-0 libpangoft2-1.0-0` (Debian/Ubuntu) or the
  equivalent package.
- **macOS:** `brew install pango`.
- **Windows:** install the GTK3 runtime; see WeasyPrint's
  [installation notes](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation).

Without them, crfpdf exits with a message that says what to install; the other six commands work regardless.

## Using crfutils

Example code used to render a CRF as HTML:
```python
from pathlib import Path
from crfutils.crfhtml import CrfHtml, CrfHtmlGenerationError

try:
    CrfHtml(Path("crf.xml")).transform_to_html_file(Path("crf.html"))
except CrfHtmlGenerationError as e:
    print(e)

# or get the HTML as a string, here as a blank CRF with the DataType and Length shown
html = CrfHtml(Path("crf.xml"), annotations=False, types=True).transform_to_html_string()
```

`CrfHtml` takes `annotations` (default True), `types` (False), `toc` (True), `visit_matrix` (True) and `mode`
(`"screen"`, or `"print"` for the static rendering crfpdf uses). Every failure raises `CrfHtmlGenerationError`;
an output that cannot be written raises its subclass `CrfHtmlWriteError`.

Schema validation:
```python
from crfutils.validate import CrfSchemaValidator, CrfSchemaLoadError

try:
    validator = CrfSchemaValidator(Path("crf.xml"))         # xsd_file=... for another schema
    result = validator.validate()                           # a ValidationResult, cached
    print(validator.validate_to_string())                   # or validate_to_file(path, as_json=True)
    print(result.is_valid, result.error_count)
except CrfSchemaLoadError as e:                             # the validation could not be run at all
    print(e)
```

Pretty-printing, reference checking and metrics follow the same pattern:
```python
from crfutils.crfpp import CrfPrettyPrinter
from crfutils.crfrefs import CrfRefChecker
from crfutils.metrics import CrfMetrics

CrfPrettyPrinter(Path("crf.xml")).pretty_print_to_file(Path("crf.pretty.xml"))

checker = CrfRefChecker(Path("crf.xml"), permissive=False)
print(checker.check_to_string(errors_only=False, max_locations=5))
print(checker.check().has_errors)

metrics = CrfMetrics(Path("crf.xml")).collect()
print(metrics.crf.forms, metrics.annotations.annotated_pct, metrics.visits.links)
```

The annotated CRF PDF:
```python
from crfutils.crfpdf import CrfPdf, CrfPdfError

try:
    pdf = CrfPdf(Path("crf.xml"), page_size="letter", title=None, visit_bookmarks=True, validate=False)
    written = pdf.write(pdf_file=Path("acrf.pdf"))          # also writes acrf.pagerefs.json beside it
    result = pdf.render()                                   # the PdfResult: pdf_bytes, page_count, forms, refs, warnings
except CrfPdfError as e:
    print(e)
```

## Running crfutils from the command line

Installing crfutils gives a command for each module:

| Command | Module | What it does |
|---|---|---|
| `crfvalidate` | `crfutils.validate` | schema validates an ODM v2.0 file |
| `crfhtml` | `crfutils.crfhtml` | renders the CRFs in an ODM v2.0 file as HTML |
| `crfpp` | `crfutils.crfpp` | pretty-prints an ODM v2.0 file |
| `crfrefs` | `crfutils.crfrefs` | checks the OID references and definitions in an ODM v2.0 file |
| `crfmetrics` | `crfutils.metrics` | reports the metrics for an ODM v2.0 CRF file |
| `crfreview` | `crfutils.crfreview` | shows a CRF in the default browser |
| `crfpdf` | `crfutils.crfpdf` | writes the annotated CRF PDF and its page-references JSON |

Each command does the same as running its module with Python's -m switch, so `crfhtml -c crf.xml` and
`python -m crfutils.crfhtml -c crf.xml` are equivalent. Every command takes `--help` and `--version`. The input
is `-c`/`--crf` on every command except crfreview, whose input is positional. Error messages go to stderr.

### crfhtml

`-c` is required and `-o` defaults to `<crf name>.html` beside the input. `--blank` leaves the SDTM annotations
out, `--types` shows each item's DataType and Length, `--no-toc` and `--no-visit-matrix` omit those sections. The
exit code is 0 when the HTML was written, 2 when it was not, and 1 for an unexpected error.

```commandline
crfhtml -c tests/data/crf_synthetic.xml -o crf.html
crfhtml -c tests/data/crf_synthetic.xml --blank
```

### crfreview

The CRF is given without `-c`, since that is how Windows passes a file to the program that opens it. The HTML
is written beside the CRF, or to the temp folder when that folder can't be written to; `--temp` always uses the
temp folder, `-o` writes to the given file, and `--no-open` writes without opening the browser. Exit codes: 0
opened (or written), 2 could not be shown (a page saying why is opened instead), 1 unexpected error. On Windows
crfreview has no console window, so a problem with no page to go on, and `--help` and `--version`, are shown in a
message box.

```commandline
crfreview tests/data/crf_synthetic.xml
crfreview --temp tests/data/crf_synthetic.xml
```

To open CRFs with a double-click on Windows: right-click an ODM `.xml` file, choose *Open with* > *Choose another
app*, browse to `crfreview.exe` in your Python's `Scripts` folder, and tick *Always*.

### crfvalidate

`-s` names another schema (the bundled ODM v2.0 schema is the default), `-o` writes the listing to a file,
`--json` emits JSON, and `-L` sets how many example locations are shown per finding (0 shows all). Exit codes: 0
valid, 1 invalid, 2 the validation could not be run.

```commandline
crfvalidate -c tests/data/crf_synthetic.xml
crfvalidate -c tests/data/crf_synthetic.xml --json -o report.json
crfvalidate -c tests/data/crf_synthetic.xml -L 0
```

The listing names the file and the schema, then each distinct problem with the places it occurs:

```
ODM v2.0 schema validation
  File:   broken.xml
  Schema: crfutils/validate/schema/odm-2-0/ODM.xsd
  Scope:  4 errors in 3 distinct problems

ERRORS (3)

  invalid_value  ItemDef   (2 occurrences)
      attribute DataType='NOT_A_DATATYPE': value must be one of ['integer', 'decimal', ...]
      - line 131  MetaDataVersion[MDV.1]/ItemDef[IT.VS.SYSBP]
      - line 170  MetaDataVersion[MDV.1]/ItemDef[IT.DM.AGE]
  ...

SUMMARY
  4 errors in broken.xml
  Schema: crfutils/validate/schema/odm-2-0/ODM.xsd
```

When the file's root element is not in the ODM v2.0 namespace and no other schema was given, the listing adds a
note saying so, since every error then stems from that.

### crfpp

`-o` writes the formatted file; without it the output goes to the console, where `-H N` limits it to the first N
lines. Exit codes: 0 written or printed, 2 the file is missing or not well-formed, 1 unexpected error.

```commandline
crfpp -c tests/data/crf_synthetic.xml -o crf.pretty.xml
crfpp -c tests/data/crf_synthetic.xml -H 40
```

### crfrefs

`--json`, `-o`, `--errors-only`, `-L` and `--permissive` as for definerefs. Exit codes: 0 no errors (warnings
allowed), 1 errors, 2 the file would not load or the report could not be written.

```commandline
crfrefs -c tests/data/crf_synthetic.xml
crfrefs -c tests/data/crf_synthetic.xml --json --errors-only
crfrefs -c nonconformant.xml --permissive
```

```
ODM v2.0 OID reference/definition check
  File:  tests/data/crf_synthetic.xml
  Model: ODM v2.0 (odmlib odm_2_0, odmlib 0.3.0)
  Scope: 46 definitions, 50 references across 9 checked attributes

WARNINGS (1)

  form_not_scheduled  IG.FORM.AE/1
      Form is not referenced by any StudyEventDef
      - ItemGroupDef in MetaDataVersion[MDV.1]/ItemGroupDef[IG.FORM.AE/1]

SUMMARY
  0 errors, 1 warning in tests/data/crf_synthetic.xml
  Checked attributes: CodeListOID, CollectionExceptionConditionOID, ItemGroupOID, ItemOID,
                      LeafID, MethodOID, StudyEventGroupOID, StudyEventOID, UnitsItemOID
  Skipped attributes: FileOID, PriorFileOID
                      (file-level - not checked)
  Unchecked elements: Include
                      (prior-version references are counted but not resolved)
```

Errors: `undefined_reference`, `undefined_document_reference`, `type_mismatch`, `duplicate_oid`,
`itemgroup_cycle`. Warnings: `orphan_definition`, `orphan_document_leaf`, `form_nested`,
`event_references_non_form`, `concept_contains_group`, and -- only when the file has a visit schedule --
`form_not_scheduled` and `event_without_forms`. Definitions and references are scoped to their MetaDataVersion,
so a file with several versions that reuse OIDs is not reported as full of duplicates.

### crfmetrics

`-o`, `--json`, `--no-forms` (omit the per-form table) and `--permissive`. Exit codes: 0 report produced, 2 it
could not be, 1 unexpected error.

```commandline
crfmetrics -c tests/data/crf_synthetic.xml
crfmetrics -c tests/data/crf_synthetic.xml --json -o metrics.json
```

```
ODM v2.0 CRF metrics
  File:     tests/data/crf_synthetic.xml
  Size:     17,718 bytes (17.3 KiB)
  Created:  2026-10-17T09:00:00  (ODM/@CreationDateTime)
  Modified: 2026-10-17T09:29:34  (file system)
  Model:    ODM v2.0 (odmlib odm_2_0, odmlib 0.3.0)

STUDY
  Study name:        SYNTH
  Protocol name:     SYNTH-001
  ...

CRF
  Forms:             4 (3 scheduled, 1 unscheduled)
  Sections:          5
  Concepts:          1
  Item definitions:  20
  Items on forms:    20 rows (20 distinct, 8 mandatory)
  Items by DataType: text 13, date 4, integer 2, float 1
  Code lists:        7 (17 items)
  ...
  Visits:            3 study events in 1 group
  Visit-form links:  5 (matrix 3 x 4, 42% filled)
  Unscheduled forms: IG.FORM.AE/1

ANNOTATIONS
  Items annotated:   20 of 20 (100%)
  By level:          form 3, section 5, concept 0, item 20, codelist item 2
  Parsed:            29 parsed, 0 partial, 1 unparsed
  NOT SUBMITTED:     3
  Datasets:          AE, CM, DM, SUPPCM, VS

FORMS (4)
  OID           Name                     Domains  Sections  Concepts  Items  Annotated  Not submitted  Visits
  IG.FORM.DM    Demographics             DM              1         0      5          5              0       1
  ...

ELEMENT COUNTS
  ...

SUMMARY
  231 elements across 124 element types (31 present, 93 absent)
  4 forms, 20 item rows, 20 item definitions, 7 code lists, 1 method, 5 visit-form links
```

A file with ClinicalData gets a `NOTE: ClinicalData (n) not examined` line under the header: crfutils handles
ODM v2.0 metadata only.

### crfpdf

`-o` defaults to `<crf name>_acrf.pdf` beside the input (a hand-made `acrf.pdf` is never overwritten by default;
pass `-o acrf.pdf` for the submission name), `--refs` to `<pdf name>.pagerefs.json` beside the PDF, and `--html`
saves the intermediate HTML. `--page-size letter|a4` (default letter), `--title TEXT` (default
"Annotated CRF - <StudyName>"), `--no-visit-bookmarks`, and `--validate` to schema validate first and refuse an
invalid file. Exit codes: 0 PDF and JSON written (warnings allowed, listed on stderr), 2 not written, 1
unexpected error.

```commandline
crfpdf -c tests/data/crf_synthetic.xml -o acrf.pdf
crfpdf -c tests/data/crf_synthetic.xml --page-size a4 --html acrf.html --validate
```

```
Wrote acrf.pdf (7 pages: 4 forms, 3 visits) and acrf.pagerefs.json (29 annotations)
```

## The page-references JSON and Define-XML

`crfpdf` writes, beside the PDF, a JSON document a Define-XML tool can use to add `def:PDFPageRef` page
references to the `def:Origin` of each collected variable. Its `schema_version` is `1.0`; it is bumped on any
change to the shape or to the key grammar.

```json
{
  "schema_version": "1.0",
  "key_format": "DATASET.VARIABLE[ where VAR = VALUE[ and ...]]",
  "generator": {"name": "crfpdf", "version": "0.1.0", "weasyprint": "68.1"},
  "crf_file": "crf.xml", "pdf_file": "acrf.pdf", "pdf_sha256": "...", "page_count": 7, "page_size": "letter",
  "study": {"oid": "ST.SYNTH", "name": "SYNTH", "protocol": "SYNTH-001", "mdv_oid": "MDV.1"},
  "leaf": {"id": "LF.acrf", "href": "acrf.pdf", "title": "Annotated CRF"},
  "forms": [{"oid": "IG.FORM.VS", "name": "Vital Signs", "domains": ["VS"], "named_destination": "F.IG.FORM.VS",
             "first_page": 5, "last_page": 5, "visits": ["SE.SCR", "SE.WK1"]}],
  "visits": [{"oid": "SE.SCR", "name": "Screening", "forms": ["IG.FORM.DM", "IG.FORM.VS"]}],
  "annotations": [{"level": "item", "source": "alias:SDTM", "form_oid": "IG.FORM.VS",
                   "group_path": ["IG.FORM.VS", "IG.SEC.VS", "IG.CON.SYSBP"], "item_oid": "IT.VS.SYSBPU",
                   "item_name": "SYSBPU", "codelist_oid": null, "coded_value": null,
                   "text": "VSORRESU = mmHg when VSTESTCD = SYSBP", "status": "parsed", "not_submitted": false,
                   "domains": [],
                   "targets": [{"dataset": "VS", "dataset_source": "prefix", "variable": "VSORRESU", "value": "mmHg",
                                "where": [{"variable": "VSTESTCD", "comparator": "EQ", "values": ["SYSBP"]}],
                                "qnam": null, "key": "VS.VSORRESU where VSTESTCD = SYSBP"}],
                   "pages": [5], "occurrences": 1}],
  "index": {"VS.VSORRESU where VSTESTCD = SYSBP": [5], "VS.VSORRESU": [5]},
  "domains": {"VS": [5]},
  "warnings": [{"check": "unparsed_annotation", "text": "see protocol section 5",
                "form_oid": "IG.FORM.DM", "item_oid": "IT.DM.NOTE"}]
}
```

- Annotations are read from the `Alias[@Context='SDTM']` elements (and the legacy `formAnnotation` /
  `formSectionAnnotation` contexts and `ItemGroupDef/@Domain`) and parsed with a lenient grammar: `DOMAIN = VS`,
  `VS (Vital Signs)`, `VSORRES when VSTESTCD = SYSBP`, `DM.SEX=M`, `RSSTRESN/RSSTRESC where RSTESTCD=ATLAS101`,
  `FTASTDEV in SUPPFT`, `CMDOSE;CMDOSTXT`, `[NOT SUBMITTED]`. Text it cannot read is kept verbatim with a warning.
- A variable's dataset is the qualifier when there is one (`DM.SEX`), else the `SUPPxx` it is placed in, else
  the longest domain the document names that is a prefix of the variable (`VSORRES` -> `VS`), else the domain of
  the innermost enclosing form or section; `dataset_source` records which rule applied.
- `index` holds every target key with its sorted pages, plus a variable-level roll-up (`VS.VSORRESU`) that is the
  union of its value-level keys. `domains` holds each domain's pages: the pages of the forms annotated with it,
  plus the pages of its targets.
- **Consumer recipe.** For a variable-level origin look up `<Domain>.<Name>`. For a value-level origin build the
  key from the ValueListDef/ItemRef/WhereClauseRef chain: `WhereClauseDef/RangeCheck` with `Comparator` `EQ`,
  `NE` or `IN`, the `CheckValue`s, and the `ItemOID`'s `Name`; conditions are sorted by variable, written
  `VAR = VALUE`, `VAR NE VALUE` or `VAR IN (A, B)` with the IN values sorted. Then emit
  `<def:DocumentRef leafID="LF.acrf"><def:PDFPageRef PageRefs="5 12" Type="PhysicalRef"/></def:DocumentRef>`,
  or `FirstPage`/`LastPage` for one contiguous range. A form-level reference can use the named destination:
  `Type="NamedDestination" PageRefs="F.IG.FORM.VS"`. Printed page numbers equal physical page numbers.

## Development

```commandline
pip install -e /path/to/odmlib          # until the odmlib release with the ODM v2.0 fixes is on PyPI
pip install -e ".[pdf,test]"
pytest                                  # the PDF tests skip when WeasyPrint or Pango is missing
CRFUTILS_BIN=.venv/bin pytest           # also compares the installed commands with python -m
CRFUTILS_UPDATE_GOLDEN=1 pytest tests/test_crfrefs.py   # regenerate the crfrefs golden reports
pytest --cov=crfutils                   # the coverage figure in the badge above
```

`tests/data/README.md` records where each test file came from. `stylesheet_changes.md` logs every edit to the
bundled stylesheet. `CRF_UTILS_PLAN.md` is the design the implementation follows.

crfutils is under development: it is not on PyPI, the command-line interface and the page-references JSON may
still change before 1.0, and the executables (PyInstaller builds, as defineutils has) are not built yet. The badges
at the top are static. The version badge is checked against `crfutils.__version__` by a test; the coverage badge
records the last local `pytest --cov=crfutils` run (the `__main__` modules run in subprocesses, which that figure
does not count), so update it when the figure moves.

## License

MIT (see `LICENSE`). The bundled stylesheet is a modified copy of Lex Jansen's `odm_2-0_transform.xsl` (MIT; see
`crfutils/crfhtml/odm_2-0_crf.xsl.LICENSE`); the bundled Liberation Sans fonts are under the SIL Open Font License
1.1 (`crfutils/crfpdf/fonts/LICENSE`); the bundled ODM v2.0 schema is CDISC's.
