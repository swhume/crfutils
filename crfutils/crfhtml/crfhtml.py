"""HTML rendering of an ODM v2.0 CRF by applying the bundled stylesheet.

A port of defineutils' definehtml: the stylesheet is compiled once, integer parameters are validated and
string parameters go through XSLT.strparam, the result is serialized only with str()/bytes(), and every
failure raises CrfHtmlGenerationError. Python owns the ids: the stylesheet emits data-* attributes, and
_assign_ids() sets the form ids (F.<oid>), the TOC and visit-matrix hrefs, and the annotation ids (A.<n>).
"""
import re
import sys
from pathlib import Path
from typing import Union

from lxml import etree

from .. import _common, _odm
from .._design import StudyDesign

# the bundled stylesheet, a reworked copy of Lex Jansen's odm_2-0_transform.xsl (see stylesheet_changes.md);
# module-level so a test can point the class at another stylesheet
STYLESHEET = Path(__file__).parent.joinpath("odm_2-0_crf.xsl")

MODES = ("screen", "print")
# the most distinct XSLT error-log messages quoted in a transform failure
MAX_XSLT_MESSAGES = 5
# characters an id may keep; anything else in an OID becomes an underscore
_ID_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
_WHITESPACE = re.compile(r"\s")


class CrfHtmlGenerationError(Exception):
    pass


class CrfHtmlWriteError(CrfHtmlGenerationError):
    """the HTML could not be written to the destination given; the CRF itself may render"""
    pass


class CrfHtml:
    def __init__(self, crf_file: Path, annotations: bool = True, types: bool = False, toc: bool = True,
                 visit_matrix: bool = True, mode: str = "screen", title_page: bool = False,
                 title: Union[str, None] = None, generated_on: Union[str, None] = None,
                 version: Union[str, None] = None, codelist_items: int = 20) -> None:
        """
        :param crf_file: Path to the ODM v2.0 file to render
        :param annotations: when False, the SDTM annotations are left out (a blank CRF)
        :param types: when True, each item shows its DataType and Length
        :param toc: when True, a table of contents is rendered when there is more than one form
        :param visit_matrix: when True, the visit matrix is rendered when the file has a visit schedule
        :param mode: "screen" for interactive controls with an embedded style; "print" for static controls
            and no style (crfpdf adds its own)
        :param title_page: when True, print mode renders a title page
        :param title: the document title; the StudyName when None
        :param generated_on: a timestamp for the footer and title page; omitted when None
        :param version: the generator version shown with the timestamp
        :param codelist_items: in print mode, a codelist with more items than this is rendered as a text field
            that names the codelist, instead of listing every item (a units list can run to hundreds)
        """
        self.crf_file = Path(crf_file)
        _common.require_file(self.crf_file, CrfHtmlGenerationError)
        if mode not in MODES:
            raise CrfHtmlGenerationError(f"The mode must be one of {', '.join(MODES)}, not {mode!r}.")
        for name, value in (("annotations", annotations), ("types", types), ("toc", toc),
                            ("visit_matrix", visit_matrix), ("title_page", title_page)):
            if not isinstance(value, bool):
                raise CrfHtmlGenerationError(f"The {name} option must be True or False, not {value!r}.")
        if isinstance(codelist_items, bool) or not isinstance(codelist_items, int) or codelist_items < 0:
            raise CrfHtmlGenerationError(f"The number of codelist items to list must be a non-negative integer, not "
                                         f"{codelist_items!r}.")
        self.annotations, self.types, self.toc, self.visit_matrix = annotations, types, toc, visit_matrix
        self.mode, self.title_page, self.codelist_items = mode, title_page, codelist_items
        self.title, self.generated_on, self.version = title, generated_on, version
        self.xslt = STYLESHEET
        self._transformer = self._load_stylesheet()
        self._result = None
        self.design = None          # the StudyDesign, after the transform
        self.form_ids = {}          # form OID -> element id, after the transform
        self.notes = []             # anything the caller should know, e.g. an OID with whitespace

    def transform_to_html_string(self) -> str:
        """
        transforms the CRF to HTML and returns the HTML as a string
        :return: string
        """
        return str(self._transform())

    def transform_to_html_file(self, html_file: Path) -> None:
        """
        transforms the CRF to HTML and writes it, UTF-8 encoded, to html_file; the destination is checked
        before the transform runs
        :param html_file: Path to the file to save the HTML output
        """
        html_file = Path(html_file)
        _common.check_destination(html_file, [self.crf_file], CrfHtmlWriteError)
        # bytes() serializes through the stylesheet's xsl:output (method="html", encoding="utf-8");
        # etree.tostring() would write XML and self-close empty elements such as <span/>
        _common.write_bytes(html_file, bytes(self._transform()), CrfHtmlWriteError)

    def transform_to_tree(self) -> etree._XSLTResultTree:
        """
        transforms the CRF and returns the HTML result tree, with the ids assigned; crfpdf post-processes
        it. Serialize it only with str() or bytes()
        :return: the HTML result tree
        """
        return self._transform()

    def _transform(self) -> etree._XSLTResultTree:
        """
        parses the CRF, confirms it is ODM v2.0 with at least one form, works out the form and visit
        order, applies the stylesheet and assigns the ids; the result is cached so every output method
        transforms once
        :return: the HTML result tree
        """
        if self._result is None:
            tree = _odm.parse_odm(self.crf_file, CrfHtmlGenerationError)
            _odm.check_odm_v2(tree.getroot(), self.crf_file, CrfHtmlGenerationError, "No HTML was generated")
            self.design = StudyDesign(_odm.design_from_lxml(tree))
            if not self.design.forms:
                raise CrfHtmlGenerationError(
                    f"{self.crf_file} has no ItemGroupDef with Type='Form'; nothing to render.\n\n"
                    f"No HTML was generated. crfhtml renders the forms of the first MetaDataVersion.")
            params = self._stylesheet_params()
            try:
                result = self._transformer(tree, **params)
            except etree.XSLTApplyError as e:
                raise CrfHtmlGenerationError(self._transform_error_message(e)) from e
            self.form_ids = _assign_ids(result)
            self._result = result
        return self._result

    def _stylesheet_params(self) -> dict:
        """
        maps the options onto the stylesheet's xsl:params. lxml evaluates each value as an XPath
        expression, so integers are passed as validated "0"/"1" strings and every string goes through
        XSLT.strparam()
        :return: dict of stylesheet parameter name to value
        """
        design = self.design
        params = {
            "displayAnnotations": "1" if self.annotations else "0",
            "displayDataTypeLength": "1" if self.types else "0",
            "displayToc": "1" if self.toc and len(design.forms) > 1 else "0",
            "displayVisitMatrix": "1" if self.visit_matrix and design.has_schedule else "0",
            "displayTitlePage": "1" if self.title_page and self.mode == "print" else "0",
            "maxCodeListItems": str(self.codelist_items),
            "mode": etree.XSLT.strparam(self.mode),
            "formOrder": etree.XSLT.strparam(_order_param(design.forms, "form", self.notes)),
            "visitOrder": etree.XSLT.strparam(_order_param(design.visits, "visit", self.notes)),
            "docTitle": etree.XSLT.strparam(self.title or ""),
            "generatedOn": etree.XSLT.strparam(self.generated_on or ""),
            "crfutilsVersion": etree.XSLT.strparam(self.version or ""),
        }
        return params

    def _transform_error_message(self, e: etree.XSLTApplyError) -> str:
        """
        builds the transform failure message; str(e) can be a single word, so the distinct messages in
        the stylesheet's error log are added
        :param e: the exception raised by the transform
        :return: string
        """
        messages = list(dict.fromkeys(entry.message.strip() for entry in self._transformer.error_log
                                      if entry.message.strip()))
        message = f"The stylesheet failed while transforming {self.crf_file}.\n  {e}"
        for line in messages[:MAX_XSLT_MESSAGES]:
            message += "\n  " + line.replace("\n", "\n  ")
        if len(messages) > MAX_XSLT_MESSAGES:
            message += f"\n  ... {len(messages) - MAX_XSLT_MESSAGES} more"
        return message

    def _load_stylesheet(self) -> etree.XSLT:
        """
        compiles the stylesheet once so every transform reuses it
        :return: the compiled stylesheet
        """
        try:
            return etree.XSLT(etree.parse(str(self.xslt)))
        except (etree.LxmlError, OSError) as e:
            raise CrfHtmlGenerationError(f"Unable to load the stylesheet {self.xslt}.\n  {e}") from e


def _order_param(oids: list, kind: str, notes: list) -> str:
    """
    the ' OID1 OID2 ' order parameter the stylesheet sorts by. An OID containing whitespace would break
    the space-delimited lookup, so the order then falls back to document order with a note
    :param oids: the OIDs in display order
    :param kind: "form" or "visit", for the note
    :param notes: the list the note is appended to
    :return: string
    """
    if any(_WHITESPACE.search(oid or "") for oid in oids):
        notes.append(f"a {kind} OID contains whitespace; {kind}s are rendered in document order")
        return ""
    return f" {' '.join(oids)} " if oids else ""


def sanitize_id(oid: str) -> str:
    """the id-safe spelling of an OID: letters, digits, '.', '_' and '-'; anything else is '_'"""
    return _ID_UNSAFE.sub("_", oid or "")


def _classes(element) -> list:
    return (element.get("class") or "").split()


def _assign_ids(result: etree._XSLTResultTree) -> dict:
    """
    sets every id in the rendered HTML: F.<sanitized OID> on each form section (with -2, -3 ... on a
    collision), the matching href on each TOC and visit-matrix link, and A.1 ... A.n on the annotation
    spans in document order. The stylesheet emits none of these, because generate-id() differs between
    processors and OIDs may contain characters an id may not
    :param result: the HTML result tree, changed in place
    :return: dict of form OID to id
    """
    root = result.getroot()
    if root is None:
        return {}
    form_ids, taken = {}, set()
    for section in root.iter("section"):
        if "form" not in _classes(section):
            continue
        oid = section.get("data-form-oid") or ""
        base = candidate = f"F.{sanitize_id(oid)}"
        suffix = 2
        while candidate in taken:
            candidate = f"{base}-{suffix}"
            suffix += 1
        taken.add(candidate)
        form_ids.setdefault(oid, candidate)
        section.set("id", candidate)
    for link in root.iter("a"):
        oid = link.get("data-form-oid")
        if oid is not None and oid in form_ids:
            link.set("href", f"#{form_ids[oid]}")
    number = 0
    for span in root.iter("span"):
        if "anno" in _classes(span):
            number += 1
            span.set("id", f"A.{number}")
    return form_ids


def print_notes(notes: list) -> None:
    """prints the notes a transform produced to stderr"""
    for note in notes:
        print(f"NOTE: {note}", file=sys.stderr)
