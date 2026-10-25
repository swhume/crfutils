"""pagerefs: the page-references document built from plain values, without rendering a PDF."""
from dataclasses import replace

from conftest import SYNTHETIC
from crfutils import _odm
from crfutils import annotations as A
from crfutils import mapping as M
from crfutils._design import AnnotationRecord, StudyDesign
from crfutils.crfpdf import AnnotationPages
from crfutils.crfpdf import pagerefs

CONCEPT = ("IG.FORM.VS", "IG.SEC.VS", "IG.CON.SYSBP")


def _build(annotations: list) -> dict:
    design = StudyDesign(_odm.design_from_lxml(_odm.parse_odm(SYNTHETIC, RuntimeError)))
    return pagerefs.build(crf_file="crf.xml", pdf_file="acrf.pdf", pdf_sha256="0" * 64, page_count=9, page_size="letter",
                          design=design, forms=[], annotations=annotations, warnings=[], generator={}, generated="")


def _anno(item_oid: str, text: str, page, origin) -> AnnotationPages:
    record = AnnotationRecord("item", "alias:SDTM", text, CONCEPT[0], CONCEPT, item_oid=item_oid)
    return AnnotationPages(record, A.parse(text, known_domains={"VS"}), f"A.{item_oid}", page, origin=origin)


def test_origins_are_grouped_by_type_and_source():
    protocol = M.ProposedOrigin("Protocol", "Sponsor", M.BASIS_ITEMREF, None)
    collected = M.ProposedOrigin("Collected", "Investigator", M.BASIS_ITEMREF, None)
    refs = _build([_anno("IT.VS.SYSBPU", "VSORRESU = mmHg when VSTESTCD = SYSBP", 5, protocol),
                   _anno("IT.VS.DIABPU", "VSORRESU = mmHg when VSTESTCD = DIABP", 6, protocol),
                   _anno("IT.VS.TEMPU", "VSORRESU when VSTESTCD = TEMP", 7, collected),
                   _anno("IT.VS.NOPAGE", "VSORRESU when VSTESTCD = HR", None, collected)])

    rolled_up = refs["origins"]["VS.VSORRESU"]
    assert [(o["type"], o["source"], o["values"], o["items"], o["pages"]) for o in rolled_up] == [
        ("Protocol", "Sponsor", ["mmHg"], ["IT.VS.SYSBPU", "IT.VS.DIABPU"], [5, 6]),
        ("Collected", "Investigator", [], ["IT.VS.TEMPU", "IT.VS.NOPAGE"], [7])]
    assert [o["type"] for o in refs["origins"]["VS.VSORRESU where VSTESTCD = TEMP"]] == ["Collected"]
    # an annotation that was not paginated still has its key and origin, with no pages
    assert refs["index"]["VS.VSORRESU where VSTESTCD = HR"] == []
    assert refs["origins"]["VS.VSORRESU where VSTESTCD = HR"][0]["pages"] == []
    assert refs["index"]["VS.VSORRESU"] == [5, 6, 7]


def test_an_annotation_without_a_proposed_origin_is_indexed_only():
    refs = _build([_anno("IT.VS.SYSBP", "VSORRESU = mmHg when VSTESTCD = SYSBP", 5, None)])
    assert refs["index"]["VS.VSORRESU"] == [5] and refs["origins"] == {}


def test_define_items_are_filed_under_the_paired_define_oid():
    protocol = M.ProposedOrigin("Protocol", "Sponsor", M.BASIS_ITEMREF, None)
    collected = M.ProposedOrigin("Collected", "Investigator", M.BASIS_ITEMREF, None)
    paired = _anno("IT.VS.SYSBPU", "VSORRESU = mmHg when VSTESTCD = SYSBP", 5, protocol)
    parsed, _ = M.pair_define_oids(paired.parsed, {"VS.VSORRESU": "IT.VS.VSORRESU.SYSBP"})
    refs = _build([replace(paired, parsed=parsed),
                   _anno("IT.VS.TEMPU", "VSORRESU when VSTESTCD = TEMP", 7, collected)])
    assert list(refs["define_items"]) == ["IT.VS.VSORRESU.SYSBP"]
    assert refs["define_items"]["IT.VS.VSORRESU.SYSBP"] == refs["origins"]["VS.VSORRESU where VSTESTCD = SYSBP"]
    assert refs["annotations"][0]["targets"][0]["define_item_oid"] == "IT.VS.VSORRESU.SYSBP"
    assert refs["annotations"][1]["targets"][0]["define_item_oid"] is None


def test_crf_identity_is_recorded():
    refs = _build([])
    assert (refs["crf_sha256"], refs["file_oid"], refs["creation_datetime"]) == (None, None, None)
    design = StudyDesign(_odm.design_from_lxml(_odm.parse_odm(SYNTHETIC, RuntimeError)))
    refs = pagerefs.build(crf_file="crf.xml", pdf_file="acrf.pdf", pdf_sha256="0" * 64, page_count=1,
                          page_size="letter", design=design, forms=[], annotations=[], warnings=[], generator={},
                          generated="", crf_sha256="a" * 64, file_oid="FILE.SYNTH.1", creation_datetime="2026")
    assert (refs["crf_sha256"], refs["file_oid"], refs["creation_datetime"]) == ("a" * 64, "FILE.SYNTH.1", "2026")
