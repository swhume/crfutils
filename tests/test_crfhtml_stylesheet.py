"""The bundled stylesheet stays XSLT 1.0, so it runs under libxslt and under Saxon alike."""
import re

from lxml import etree

from crfutils.crfhtml import STYLESHEET

XSL_NS = "http://www.w3.org/1999/XSL/Transform"

# XSLT 2.0 / XPath 2.0 constructs that libxslt would reject or silently misrender
FORBIDDEN_ELEMENTS = {"function", "for-each-group", "analyze-string", "result-document", "sequence", "perform-sort",
                      "next-match", "character-map", "import-schema"}
FORBIDDEN_FUNCTIONS = re.compile(r"\b(tokenize|matches|replace|current-group|current-grouping-key|string-join|"
                                 r"distinct-values|exists|empty|xs:\w+)\s*\(")


def _stylesheet():
    return etree.parse(str(STYLESHEET))


def test_declares_version_1_0():
    assert _stylesheet().getroot().get("version") == "1.0"


def test_compiles_under_libxslt():
    assert etree.XSLT(_stylesheet()) is not None


def test_output_is_html5():
    output = _stylesheet().getroot().find(f"{{{XSL_NS}}}output")
    assert (output.get("method"), output.get("version"), output.get("encoding")) == ("html", "5", "UTF-8")


def test_no_xslt_2_elements():
    found = {etree.QName(e).localname for e in _stylesheet().iter()
             if isinstance(e.tag, str) and etree.QName(e).namespace == XSL_NS}
    assert not found & FORBIDDEN_ELEMENTS


def test_no_xpath_2_functions():
    for element in _stylesheet().iter():
        if not isinstance(element.tag, str):
            continue
        for value in element.attrib.values():
            assert not FORBIDDEN_FUNCTIONS.search(value), value


def test_keys_are_anchored_at_the_first_study_and_mdv():
    keys = _stylesheet().getroot().findall(f"{{{XSL_NS}}}key")
    assert {k.get("name") for k in keys} == {"igd", "itd", "cl", "sed"}
    for key in keys:
        assert key.get("match").startswith("/odm:ODM/odm:Study[1]/odm:MetaDataVersion[1]/odm:")


def test_stylesheet_emits_no_ids():
    # Python owns the ids: an id attribute or generate-id() in the stylesheet would break that
    for element in _stylesheet().iter():
        if not isinstance(element.tag, str):
            continue
        assert "id" not in element.attrib, etree.tostring(element)[:80]
        assert not (etree.QName(element).localname == "attribute" and element.get("name") == "id")
        assert not any("generate-id(" in value for value in element.attrib.values())


def test_params():
    names = {p.get("name") for p in _stylesheet().getroot().findall(f"{{{XSL_NS}}}param")}
    assert names == {"displayAnnotations", "displayDataTypeLength", "displayToc", "displayVisitMatrix",
                     "displayTitlePage", "maxCodeListItems", "mode", "formOrder", "visitOrder", "docTitle",
                     "generatedOn", "crfutilsVersion"}
