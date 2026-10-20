# Changes to the bundled stylesheet

`crfutils/crfhtml/odm_2-0_crf.xsl` started as a byte-identical copy of Lex Jansen's
`stylesheet/odm_2-0_transform.xsl` from [cdisc360i-pocs](https://github.com/lexjansen/cdisc360i-pocs) (MIT; see
`crfutils/crfhtml/odm_2-0_crf.xsl.LICENSE`). Every edit to it is recorded here.

## 2026-10-17: rework for crfutils (Phase 2 of CRF_UTILS_PLAN.md)

The stylesheet was rewritten around the original's rendering. What changed, and why:

1. **`version="1.0"`** instead of `version="2.0"`. The original used only XSLT 1.0 constructs; declaring 1.0 is
   what lets libxslt run it without a forwards-compatibility warning, and keeps it runnable under Saxon.
   `tests/test_crfhtml_stylesheet.py` fails on any XSLT 2.0 element or XPath 2.0 function.
2. **Radio labels.** The decode was emitted as the content of the void `<input type="radio">`, which libxslt
   drops. Each option is now `<label class="option"><input type="radio"/><span class="decode">…</span></label>`.
3. **`xsl:key` lookups** (`igd`, `itd`, `cl`, `sed`) anchored at `/odm:ODM/odm:Study[1]/odm:MetaDataVersion[1]`
   replace the `//odm:ItemGroupDef[@OID=$x]` searches, which were quadratic.
4. **One group renderer** (`group-rows`) for Form, Section, Concept and any other Type. The original rendered
   `ItemRef`s only under a Concept, so items placed directly on a Form or Section (every DataExchange-ODM
   example) were dropped. Children render in `@OrderNumber` order with `<xsl:sort data-type="number"/>`, so
   children without one come first (NaN) and otherwise document order is kept; a form is one table, with a
   heading row per nested group, so `thead` repeats on continuation pages when printed.
5. **Cycle and depth guards.** A group already on the path renders a `cycle` marker row and is not entered; so
   does a group nested deeper than 10 (`too-deep`). An undefined ItemGroupDef, ItemDef or CodeList renders a
   `missing` marker instead of nothing.
6. **`<title>`** is `docTitle`, else `Study/@StudyName`, else the first form's name (the original's
   `//ItemGroupDef[@Type='Form']/@Name`). A document header shows the study, protocol and MetaDataVersion.
7. **Form order** comes from the `formOrder` parameter (`' OID1 OID2 '`), sorted with
   `string-length(substring-before($formOrder, concat(' ', @OID, ' ')))`; an empty parameter keeps document
   order, so the stylesheet also works with no caller-side ordering. crfhtml orders forms by the visit schedule.
8. **Table of contents and visit matrix** (`displayToc`, `displayVisitMatrix`, `visitOrder`). The matrix shows
   `X` or `(X)` (Mandatory="No") per form and StudyEventDef.
9. **Annotation sources.** Form: `Alias[@Context='formAnnotation' or 'SDTM']`, else `@Domain`; Section:
   `formSectionAnnotation` or `SDTM`, else `@Domain`; Concept: `SDTM`; ItemDef: every `SDTM` alias;
   CodeListItem: `SDTM` aliases, listed in the annotation column on screen and beside the option in print.
   Completion instructions come from `formSectionCompletionInstruction`, `completionInstructions` and
   `ItemDef/CRFCompletionInstructions`. The original read only the legacy contexts.
10. **Every annotation is a `<span class="anno anno-<level>">`** carrying `data-level`, `data-source`,
    `data-text`, `data-form-oid`, `data-group-path`, and for items `data-item-oid`, for codelist items
    `data-codelist-oid` and `data-coded-value`. Forms are `<section class="form" data-form-oid data-form-name>`;
    TOC and matrix links carry `data-form-oid`. **No ids are emitted**: crfhtml assigns `F.<oid>`, `A.<n>` and
    the hrefs in Python. The `id="{ItemDef/@Name}"` on `<select>` was removed (it could repeat).
11. **Controls.** `maxlength` only when `@Length` exists (the original emitted `maxlength=""`); `float`,
    `decimal` and `double` are number inputs; `datetime` is `datetime-local`; `time` is a time input; `boolean`
    is a Yes/No pair; `@PreSpecifiedValue` stays a read-only field.
12. **Print mode** (`mode='print'`): no embedded `<style>` (crfpdf injects `acrf.css`), a title page
    (`displayTitlePage`), static controls (`span.field`, `span.box`) with every codelist item listed, and a
    footer with `generatedOn` and `crfutilsVersion`. Coding information (`Coding`, codelist names) is not rendered.
13. **Screen style** keeps the original's look and adds rules for the new elements plus a minimal `@media print`
    block (a page per form, rows kept together, repeating `thead`) for printing from a browser.
14. **Long codelists in print** (`maxCodeListItems`, default 20). A codelist with more items than the cap renders as a
    text field with "Select from <Name> (N terms)" beneath it, instead of listing every item: a units codelist in a
    real CRF ran to hundreds of boxes over several pages. Its codelist-item annotations are then listed in the
    annotation column, as on screen, so the set of `data-*` annotations is unchanged. crfpdf's `--codelist-items N`
    sets the cap.
