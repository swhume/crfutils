"""Submission-ready annotated CRF PDF from an ODM v2.0 CRF, plus the page-references JSON.

The pipeline: crfhtml renders the CRF in print mode (title page, TOC, visit matrix, one page-broken section per
form, static controls); crfpdf parses every annotation, resolves its SDTM targets and proposed origin with
mapping.py (the item's mapping instructions and the conditions its concept group implies), colours it by
domain, injects the print CSS and the
bundled fonts, renders with WeasyPrint, reads each annotation's physical page from WeasyPrint's layout, prunes
the annotation anchors so only the forms become named destinations, and adds bookmarks, the page mode and the
viewer preferences in a pypdf pass. WeasyPrint and pypdf are imported only inside render(), so the other
commands never need them.
"""
import hashlib
import io
import json
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Union

from .. import __version__, _common
from .. import annotations as A
from .. import mapping as M
from .._design import CONCEPT, AnnotationRecord, ChildRef
from ..crfhtml import CrfHtml, CrfHtmlGenerationError
from . import pagerefs

CSS_FILE = Path(__file__).parent.joinpath("acrf.css")
FONT_DIR = Path(__file__).parent.joinpath("fonts")
FONT_FAMILY = "CRFUtils Sans"
# the bundled Liberation Sans faces (SIL OFL 1.1; see fonts/LICENSE), served under the family alias
FONT_FACES = [("LiberationSans-Regular.ttf", "normal", "normal"),
              ("LiberationSans-Bold.ttf", "bold", "normal"),
              ("LiberationSans-Italic.ttf", "normal", "italic"),
              ("LiberationSans-BoldItalic.ttf", "bold", "italic")]
PAGE_SIZES = {"letter": "letter", "a4": "A4"}
# the fills for the first four domains on a form, in order of first appearance (SDTM-MSG style)
DOMAIN_COLOURS = 4
INSTALL_HELP = ("crfpdf needs WeasyPrint and pypdf, which are optional: install them with\n\n"
                "    pip install \"crfutils[pdf]\"\n\n"
                "WeasyPrint also needs the Pango system libraries; see\n"
                "https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation")
MAX_WARNINGS_SHOWN = 5

ANNOTATION_NOT_PAGINATED = "annotation_not_paginated"
UNPARSED_ANNOTATION = "unparsed_annotation"
DATASET_UNRESOLVED = "dataset_unresolved"
SDTM_ALIAS_DISAGREES = "sdtm_alias_disagrees"
FORM_ORDER = "form_page_order"


class CrfPdfError(Exception):
    pass


class CrfPdfWriteError(CrfPdfError):
    """an output could not be written to the destination given; the CRF itself may render"""
    pass


@dataclass(frozen=True)
class FormPages:
    oid: str
    name: Union[str, None]
    domains: list
    named_destination: str
    first_page: int
    last_page: int
    visits: list


@dataclass(frozen=True)
class AnnotationPages:
    record: AnnotationRecord
    parsed: A.ParsedAnnotation      # corrected by the mapping instructions and enriched by the concept group
    id: str
    page: Union[int, None]
    instruction: Union[M.MappingInstruction, None] = None   # the item's mapping instructions
    item_ref: Union[ChildRef, None] = None                  # the ItemRef the annotated item is rendered from
    origin: Union[M.ProposedOrigin, None] = None


@dataclass(frozen=True)
class Warning:
    check: str
    text: str
    form_oid: Union[str, None]
    item_oid: Union[str, None]


@dataclass
class PdfResult:
    pdf_bytes: bytes
    html: str
    page_count: int
    forms: list                     # FormPages, in display order
    annotations: list               # AnnotationPages, in document order
    refs: dict                      # the page-references document
    weasyprint_version: str
    warnings: list = field(default_factory=list)


def _import_engines():
    """imports WeasyPrint and pypdf; a module-level function so a test can make it fail as a missing Pango does"""
    import pypdf
    import weasyprint
    return weasyprint, pypdf


class CrfPdf:
    def __init__(self, crf_file: Path, page_size: str = "letter", title: Union[str, None] = None,
                 visit_bookmarks: bool = True, validate: bool = False, codelist_items: int = 20) -> None:
        """
        :param crf_file: Path to the ODM v2.0 CRF to render
        :param page_size: "letter" or "a4"
        :param title: the document title; "Annotated CRF - <StudyName>" when None
        :param visit_bookmarks: when True, a Visits bookmark tree is added when the file has a visit schedule
        :param validate: when True, the file is schema validated first and refused when invalid
        :param codelist_items: a codelist with more items than this is rendered as a text field that names the
            codelist, instead of listing every item
        """
        self.codelist_items = codelist_items
        self.crf_file = Path(crf_file)
        _common.require_file(self.crf_file, CrfPdfError)
        if page_size.lower() not in PAGE_SIZES:
            raise CrfPdfError(f"The page size must be one of {', '.join(PAGE_SIZES)}, not {page_size!r}.")
        self.page_size = page_size.lower()
        self.title = title
        self.visit_bookmarks = visit_bookmarks
        self.validate = validate
        self._result = None

    # --- outputs ---------------------------------------------------------------------------------------

    def default_pdf(self) -> Path:
        """<crf stem>_acrf.pdf beside the input; a hand-made acrf.pdf is never overwritten by default"""
        return self.crf_file.with_name(f"{self.crf_file.stem}_acrf.pdf")

    @staticmethod
    def default_refs(pdf_file: Path) -> Path:
        """<pdf stem>.pagerefs.json beside the PDF"""
        pdf_file = Path(pdf_file)
        return pdf_file.with_name(f"{pdf_file.stem}.pagerefs.json")

    def write(self, pdf_file: Path = None, refs_file: Path = None, html_file: Path = None) -> dict:
        """
        renders and writes the PDF, the page-references JSON and, when asked, the intermediate HTML. The
        destinations are checked before the render runs
        :return: dict of "pdf", "refs" and "html" to the paths written (html only when requested)
        """
        pdf_file = Path(pdf_file) if pdf_file else self.default_pdf()
        refs_file = Path(refs_file) if refs_file else self.default_refs(pdf_file)
        html_file = Path(html_file) if html_file else None
        outputs = [p for p in (pdf_file, refs_file, html_file) if p is not None]
        for out in outputs:
            _common.check_destination(out, [self.crf_file] + [o for o in outputs if o is not out], CrfPdfWriteError)
        result = self.render(pdf_name=str(pdf_file))
        _common.write_bytes(pdf_file, result.pdf_bytes, CrfPdfWriteError)
        _common.write_text(refs_file, json.dumps(result.refs, indent=2) + "\n", CrfPdfWriteError)
        written = {"pdf": pdf_file, "refs": refs_file}
        if html_file is not None:
            _common.write_text(html_file, result.html, CrfPdfWriteError)
            written["html"] = html_file
        return written

    # --- the pipeline ----------------------------------------------------------------------------------

    def render(self, pdf_name: Union[str, None] = None) -> PdfResult:
        """
        renders the PDF in memory and builds the page-references document; cached, so write() and the report
        render once
        :param pdf_name: the PDF file name recorded in the JSON (the default PDF path when None)
        """
        if self._result is not None:
            return self._result
        try:
            weasyprint, pypdf = _import_engines()
        except (ImportError, OSError) as e:
            raise CrfPdfError(f"{type(e).__name__}: {e}\n\n{INSTALL_HELP}") from e
        if self.validate:
            self._validate()
        generated = datetime.now().astimezone().isoformat(timespec="seconds")
        renderer = self._renderer(generated)
        try:
            tree = renderer.transform_to_tree()
        except CrfHtmlGenerationError as e:
            raise CrfPdfError(str(e).replace("No HTML was generated", "No PDF was generated")) from e
        design = renderer.design
        warnings = []
        annotations = self._annotate(tree, design, warnings)
        self._inject_style(tree)
        self._add_meta(tree, design, generated)
        html = str(tree)
        document = weasyprint.HTML(string=html, base_url=str(self.crf_file.parent)).render()
        page_of = {}
        for number, page in enumerate(document.pages, 1):
            for name in page.anchors:
                page_of.setdefault(name, number)
        forms = self._form_pages(design, renderer.form_ids, page_of, len(document.pages), warnings)
        paginated = []
        for anno in annotations:
            page = page_of.get(anno.id)
            if page is None:
                warnings.append(Warning(ANNOTATION_NOT_PAGINATED, anno.record.text, anno.record.form_oid,
                                        anno.record.item_oid))
            paginated.append(replace(anno, page=page))
        # only the forms become named destinations; the annotation anchors have served their purpose
        for page in document.pages:
            for name in list(page.anchors):
                if not name.startswith("F."):
                    del page.anchors[name]
        pdf_bytes = self._finish_pdf(pypdf, document.write_pdf(), design, forms, renderer.form_ids)
        pdf_name = pdf_name or str(self.default_pdf())
        refs = pagerefs.build(
            crf_file=str(self.crf_file), pdf_file=pdf_name, pdf_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
            page_count=len(document.pages), page_size=self.page_size, design=design, forms=forms,
            annotations=paginated, warnings=warnings,
            generator={"name": "crfpdf", "version": __version__, "weasyprint": weasyprint.__version__},
            generated=generated)
        self._result = PdfResult(pdf_bytes=pdf_bytes, html=html, page_count=len(document.pages), forms=forms,
                                 annotations=paginated, refs=refs, weasyprint_version=weasyprint.__version__,
                                 warnings=warnings)
        return self._result

    def _validate(self) -> None:
        from ..validate import CrfSchemaValidationError, CrfSchemaValidator
        try:
            result = CrfSchemaValidator(self.crf_file).validate()
        except CrfSchemaValidationError as e:
            raise CrfPdfError(f"{e}\n\nNo PDF was generated.") from e
        if result.has_errors:
            raise CrfPdfError(f"{self.crf_file} is not valid ODM v2.0: {result.error_count} schema validation "
                              f"error{'s' if result.error_count != 1 else ''}.\n\nNo PDF was generated. Run "
                              f"crfvalidate to list them:\n\n    crfvalidate -c {self.crf_file}")

    def _renderer(self, generated: str) -> CrfHtml:
        try:
            renderer = CrfHtml(self.crf_file, mode="print", title_page=True, title=self.title or "",
                               generated_on=generated, version=__version__, codelist_items=self.codelist_items)
        except CrfHtmlGenerationError as e:
            raise CrfPdfError(str(e)) from e
        return renderer

    def _annotate(self, tree, design, warnings: list) -> list:
        """
        parses every annotation span, checks an item annotation against the item's mapping instructions, adds
        the conditions its concept group implies, proposes an origin, records it, and sets data-domain-index on
        the span: 1-4 by the order the domain first appears on the form, 0 when the annotation names no
        resolvable domain
        """
        if self.title is None and design.data.study_name:
            self._set_title(tree, f"Annotated CRF - {design.data.study_name}")
        known = design.known_domains
        concepts = [group.oid for group in design.data.groups.values() if group.type == CONCEPT]
        annotations = []
        for section in tree.getroot().iter("section"):
            if "form" not in (section.get("class") or "").split():
                continue
            spans, pairs, instructions = [], [], []
            for span in section.iter("span"):
                if "anno" not in (span.get("class") or "").split():
                    continue
                record = _record(span)
                level = "group" if record.level in ("form", "section", "concept") else "item"
                context = design.context_domain(record.group_path)
                parsed = A.parse(record.text, level=level, source=record.source, context_domain=context,
                                 known_domains=known)
                item = design.data.items.get(record.item_oid) if record.item_oid else None
                instruction = M.classify(M.instructions_text(item.aliases)) if item is not None else None
                if record.level == "item":
                    parsed, disagreement = M.correct(parsed, instruction, context, known)
                    if disagreement:
                        warnings.append(Warning(SDTM_ALIAS_DISAGREES, disagreement, record.form_oid, record.item_oid))
                spans.append(span)
                pairs.append((record, parsed))
                instructions.append(instruction)
            order = []
            for span, (record, _), parsed, instruction in zip(spans, pairs, M.enrich(pairs, concepts), instructions):
                domains = list(parsed.domains) + [t.dataset for t in parsed.targets if t.dataset]
                index = 0
                if domains:
                    if domains[0] not in order:
                        order.append(domains[0])
                    index = (order.index(domains[0]) % DOMAIN_COLOURS) + 1
                span.set("data-domain-index", str(index))
                if parsed.status in (A.PARTIAL, A.UNPARSED):
                    warnings.append(Warning(UNPARSED_ANNOTATION, record.text, record.form_oid, record.item_oid))
                if A.DATASET_UNRESOLVED in parsed.warnings:
                    warnings.append(Warning(DATASET_UNRESOLVED, record.text, record.form_oid, record.item_oid))
                item_ref = design.item_ref(record.group_path[-1], record.item_oid) if record.item_oid else None
                origin = M.propose(parsed, instruction, item_ref.origins if item_ref is not None else ())
                annotations.append(AnnotationPages(record, parsed, span.get("id"), None, instruction=instruction,
                                                   item_ref=item_ref, origin=origin))
        return annotations

    @staticmethod
    def _set_title(tree, title: str) -> None:
        for element in tree.getroot().iter("title"):
            element.text = title
            break
        for element in tree.getroot().iter("h1"):
            if "doc-title" in (element.get("class") or "").split():
                element.text = title
                break

    def _inject_style(self, tree) -> None:
        """prepends the generated @page and @font-face rules and acrf.css to the head"""
        size = PAGE_SIZES[self.page_size]
        rules = [f"@page {{ size: {size}; }}", f"@page matrix {{ size: {size} landscape; }}"]
        for file_name, weight, style in FONT_FACES:
            rules.append(f'@font-face {{ font-family: "{FONT_FAMILY}"; src: url("{(FONT_DIR / file_name).as_uri()}"); '
                         f"font-weight: {weight}; font-style: {style}; }}")
        css = "\n".join(rules) + "\n" + CSS_FILE.read_text(encoding="utf-8")
        head = next(tree.getroot().iter("head"))
        from lxml import etree
        style = etree.SubElement(head, "style")
        style.text = css

    def _add_meta(self, tree, design, generated: str) -> None:
        """the PDF metadata WeasyPrint reads from <meta> elements"""
        from lxml import etree
        head = next(tree.getroot().iter("head"))
        root = design.data
        values = [("author", self._originator()), ("description", f"Annotated CRF for study {root.study_name or ''}"
                                                                   f" ({root.protocol_name or ''})"),
                  ("keywords", "annotated CRF, CDISC, ODM, SDTM"), ("generator", f"crfutils crfpdf {__version__}"),
                  ("dcterms.created", generated)]
        for name, content in values:
            if content:
                etree.SubElement(head, "meta", name=name, content=content)

    def _originator(self) -> Union[str, None]:
        from lxml import etree
        try:
            return etree.parse(str(self.crf_file)).getroot().get("Originator")
        except (etree.LxmlError, OSError):
            return None

    @staticmethod
    def _form_pages(design, form_ids: dict, page_of: dict, page_count: int, warnings: list) -> list:
        """
        the page range of each form: from its anchor's page to the page before the next form's anchor, or the
        last page. Every form starts a page and the forms are the last content, so that holds; the order is
        checked all the same
        """
        firsts = []
        for oid in design.forms:
            anchor = form_ids.get(oid)
            first = page_of.get(anchor)
            if first is None:
                warnings.append(Warning(FORM_ORDER, f"form {oid} has no page", oid, None))
                first = firsts[-1][1] if firsts else 1
            elif firsts and first < firsts[-1][1]:
                warnings.append(Warning(FORM_ORDER, f"form {oid} starts before the previous form", oid, None))
            firsts.append((oid, first))
        forms = []
        for position, (oid, first) in enumerate(firsts):
            last = firsts[position + 1][1] - 1 if position + 1 < len(firsts) else page_count
            group = design.data.groups[oid]
            domains = []
            for source, text in design.group_annotations(oid):
                domains += A.parse(text, level="group", source=source).domains
            for row in design.groups_on(oid):
                domain = design.group_domain(row.oid)
                if domain:
                    domains.append(domain)
            forms.append(FormPages(oid=oid, name=group.name, domains=list(dict.fromkeys(domains)),
                                   named_destination=form_ids.get(oid, ""), first_page=first, last_page=max(first, last),
                                   visits=list(design.form_visits.get(oid, []))))
        return forms

    def _finish_pdf(self, pypdf, pdf_bytes: bytes, design, forms: list, form_ids: dict) -> bytes:
        """the pypdf pass: bookmarks, the page mode that opens the bookmarks panel, the viewer preference that
        shows the title, and a PDF 1.7 header"""
        from pypdf.generic import Fit
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        writer = pypdf.PdfWriter(clone_from=reader)
        first_pages = {form.oid: form.first_page for form in forms}
        toc_page = 2 if len(design.forms) > 1 else None
        if toc_page and toc_page < (forms[0].first_page if forms else 1):
            writer.add_outline_item("Table of Contents", toc_page - 1, fit=Fit.xyz())
        if design.has_schedule and forms and forms[0].first_page > (3 if toc_page else 2):
            writer.add_outline_item("Visit Matrix", (3 if toc_page else 2) - 1, fit=Fit.xyz())
        parent = writer.add_outline_item("Forms", forms[0].first_page - 1 if forms else 0, fit=Fit.xyz())
        for form in forms:
            writer.add_outline_item(form.name or form.oid, form.first_page - 1, parent=parent, fit=Fit.xyz())
        if self.visit_bookmarks and design.has_schedule:
            visits = writer.add_outline_item("Visits", forms[0].first_page - 1 if forms else 0, fit=Fit.xyz())
            for visit in design.visits:
                refs = design.schedule.get(visit, [])
                if not refs:
                    continue
                node = writer.add_outline_item(design.data.events[visit].name or visit, first_pages[refs[0].oid] - 1,
                                               parent=visits, fit=Fit.xyz())
                for ref in refs:
                    name = design.data.groups[ref.oid].name or ref.oid
                    if ref.mandatory == "No":
                        name += " (optional)"
                    writer.add_outline_item(name, first_pages[ref.oid] - 1, parent=node, fit=Fit.xyz())
        writer.page_mode = "/UseOutlines"
        writer.create_viewer_preferences()
        writer.viewer_preferences.display_doctitle = True
        writer.pdf_header = "%PDF-1.7"
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()


def _record(span) -> AnnotationRecord:
    """the annotation record a rendered span carries in its data-* attributes"""
    return AnnotationRecord(
        level=span.get("data-level"), source=span.get("data-source"), text=span.get("data-text") or "",
        form_oid=span.get("data-form-oid"), group_path=tuple((span.get("data-group-path") or "").split(" > ")),
        item_oid=span.get("data-item-oid"), codelist_oid=span.get("data-codelist-oid"),
        coded_value=span.get("data-coded-value"))


def report(result: PdfResult, written: dict) -> None:
    """prints the one-line outcome to stdout and the warnings to stderr"""
    forms, visits = len(result.forms), len(result.refs["visits"])
    print(f"Wrote {written['pdf']} ({result.page_count} page{'s' if result.page_count != 1 else ''}: "
          f"{forms} form{'s' if forms != 1 else ''}, {visits} visit{'s' if visits != 1 else ''}) and "
          f"{written['refs']} ({len(result.refs['annotations'])} annotation"
          f"{'s' if len(result.refs['annotations']) != 1 else ''})")
    if "html" in written:
        print(f"Wrote {written['html']}")
    if result.warnings:
        print(f"{len(result.warnings)} warning{'s' if len(result.warnings) != 1 else ''}:", file=sys.stderr)
        for warning in result.warnings[:MAX_WARNINGS_SHOWN]:
            where = warning.item_oid or warning.form_oid or ""
            print(f"  {warning.check}  {where}: {warning.text}", file=sys.stderr)
        if len(result.warnings) > MAX_WARNINGS_SHOWN:
            print(f"  ... and {len(result.warnings) - MAX_WARNINGS_SHOWN} more (all are in the JSON)", file=sys.stderr)
