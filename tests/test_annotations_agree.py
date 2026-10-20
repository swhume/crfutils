"""
The annotations StudyDesign derives from the design are exactly the annotations the rendered HTML carries in its
data-* attributes, in both modes, on every fixture. crfmetrics counts the former and crfpdf reads the latter, so
the two must never drift apart. No WeasyPrint is needed.
"""
from collections import Counter

import pytest

from conftest import FIXTURES, fixture_path
from crfutils import _odm
from crfutils._design import AnnotationRecord, StudyDesign


def _from_html(doc) -> Counter:
    records = []
    for span in doc.cssselect("span.anno"):
        records.append(AnnotationRecord(
            level=span.get("data-level"), source=span.get("data-source"), text=span.get("data-text"),
            form_oid=span.get("data-form-oid"), group_path=tuple(span.get("data-group-path").split(" > ")),
            item_oid=span.get("data-item-oid"), codelist_oid=span.get("data-codelist-oid"),
            coded_value=span.get("data-coded-value")))
    return Counter(records)


@pytest.mark.parametrize("mode", ["screen", "print"])
@pytest.mark.parametrize("name", FIXTURES)
def test_design_annotations_equal_the_html_annotations(name, mode, render):
    design = StudyDesign(_odm.design_from_lxml(_odm.parse_odm(fixture_path(name), RuntimeError)))

    expected = Counter(design.annotations())
    rendered = _from_html(render(fixture_path(name), mode=mode))

    assert rendered == expected
    # the span text is the annotation text
    assert all(span.text_content() == span.get("data-text")
               for span in render(fixture_path(name), mode=mode).cssselect("span.anno"))


def test_capped_codelist_keeps_its_annotations_in_print(edited_crf, render):
    from lxml import etree
    from crfutils._odm import tag

    def edit(tree):
        mdv = tree.getroot().find(".//{http://www.cdisc.org/ns/odm/v2.0}MetaDataVersion")
        codelist = [c for c in mdv.findall(tag("CodeList")) if c.get("OID") == "CL.SEX"][0]
        for n in range(30):
            item = etree.SubElement(codelist, tag("CodeListItem"), CodedValue=f"U{n}")
            etree.SubElement(item, tag("Alias"), Context="SDTM", Name=f"DM.SEX=U{n}")

    crf = edited_crf(edit)
    design = StudyDesign(_odm.design_from_lxml(_odm.parse_odm(crf, RuntimeError)))
    assert _from_html(render(crf, mode="print")) == Counter(design.annotations())


def test_the_fixtures_have_annotations_to_compare(render):
    assert sum(len(render(fixture_path(name)).cssselect("span.anno")) for name in FIXTURES) > 150
