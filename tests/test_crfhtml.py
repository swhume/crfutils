"""crfhtml: the rendered HTML, its ids and links, the options, the refusals, and the command."""
import re
import sys
from pathlib import Path

import pytest
from lxml import etree, html

from conftest import FIXTURES, SYNTHETIC, fixture_path
from crfutils import _odm
from crfutils._design import StudyDesign
from crfutils.crfhtml import CrfHtml, CrfHtmlGenerationError, CrfHtmlWriteError, STYLESHEET, sanitize_id

NS = {"odm": _odm.ODM_NS}
ID = re.compile(r"^[A-Za-z0-9._-]+$")


def _design(path) -> StudyDesign:
    return StudyDesign(_odm.design_from_lxml(_odm.parse_odm(path, RuntimeError)))


def _forms(doc) -> list:
    return doc.cssselect("section.form")


def _rows(form) -> list:
    return form.cssselect("tbody > tr")


# structure

@pytest.mark.parametrize("name", FIXTURES)
def test_every_fixture_renders_with_one_section_per_form_in_design_order(name, render):
    design = _design(fixture_path(name))
    doc = render(fixture_path(name))

    assert [form.get("data-form-oid") for form in _forms(doc)] == design.forms
    for form in _forms(doc):
        oid = form.get("data-form-oid")
        assert form.get("data-form-name") == design.data.groups[oid].name
        assert form.cssselect("h2.form-title")[0].text_content() == design.data.groups[oid].name
        # one table per form, with a heading row per nested group and a row per item, in walk order
        assert len(form.cssselect("table.crf")) == 1
        rows = _rows(form)
        walk = design.walk(oid)
        assert len(rows) == len(walk)
        for row, node in zip(rows, walk):
            if node.kind == "item":
                assert "item" in row.get("class").split()
                assert row.get("data-item-oid") == node.oid
                assert row.get("data-group-path") == " > ".join(node.path)
            else:
                assert "group-head" in row.get("class").split()
                assert row.get("data-group-oid") == node.oid


def test_output_is_html5(render):
    text = CrfHtml(SYNTHETIC).transform_to_html_string()

    assert text.startswith("<!DOCTYPE html>")
    assert "<meta charset=\"utf-8\">" in text
    assert "<span/>" not in text and "<a/>" not in text


def test_title_is_the_study_name(render):
    doc = render(SYNTHETIC)
    assert doc.findtext(".//title") == "SYNTH"
    assert doc.cssselect("h1.doc-title")[0].text == "SYNTH"
    assert "SYNTH-001" in doc.cssselect("p.doc-meta")[0].text_content()


def test_form_and_section_item_refs_are_rendered(render):
    # vocabulary A files put items on Concepts; the synthetic file also puts them directly on Sections
    doc = render(SYNTHETIC)
    dm = [f for f in _forms(doc) if f.get("data-form-oid") == "IG.FORM.DM"][0]

    assert [row.get("data-item-oid") for row in dm.cssselect("tr.item")] == \
           ["IT.DM.BRTHDTC", "IT.DM.SEX", "IT.DM.AGE", "IT.DM.AGEU", "IT.DM.NOTE"]
    heads = dm.cssselect("tr.group-head")
    assert [h.get("data-group-oid") for h in heads] == ["IG.SEC.DM"]
    assert "type-Section" in heads[0].get("class") and "depth-1" in heads[0].get("class")


def test_mixed_children_render_in_document_order(render):
    doc = render(SYNTHETIC)
    vs = [f for f in _forms(doc) if f.get("data-form-oid") == "IG.FORM.VS"][0]

    assert [(row.get("data-item-oid") or row.get("data-group-oid")) for row in _rows(vs)] == \
           ["IG.SEC.VS", "IT.VS.VSPERF", "IG.CON.SYSBP", "IT.VS.SYSBP", "IT.VS.SYSBPU", "IT.VS.VSPOS", "IT.VS.VSDTC"]
    assert _rows(vs)[3].get("data-group-path") == "IG.FORM.VS > IG.SEC.VS > IG.CON.SYSBP"


def test_question_text_prefers_prompt_then_question_then_name(render):
    doc = render(SYNTHETIC)
    questions = {row.get("data-item-oid"): row.cssselect("td.question .question-text")[0].text
                 for row in doc.cssselect("tr.item")}

    assert questions["IT.VS.SYSBP"] == "Systolic BP"        # Prompt
    assert questions["IT.DM.SEX"] == "Sex"                   # Question
    assert "* " in doc.cssselect("tr.item[data-item-oid='IT.DM.SEX'] td.question")[0].text_content()
    assert doc.cssselect("tr.item[data-item-oid='IT.VS.SYSBP'] .instruction")[0].text == "Record after 5 minutes seated."


def test_group_description_and_instructions(render):
    doc = render(SYNTHETIC)
    cm = doc.cssselect("tr.group-head[data-group-oid='IG.SEC.CM']")[0]

    assert cm.cssselect(".group-title")[0].text == "Medication"
    assert cm.cssselect(".description")[0].text == "Record all medications taken."
    assert cm.cssselect(".instruction")[0].text == "One row per medication."


# controls

def test_screen_controls(render):
    doc = render(SYNTHETIC)
    row = lambda oid: doc.cssselect(f"tr.item[data-item-oid='{oid}'] td.response")[0]

    assert row("IT.AE.AETERM").cssselect("input[type='text']")[0].get("maxlength") == "200"
    assert row("IT.VS.VSDTC").cssselect("input[type='date']")
    assert row("IT.VS.SYSBP").cssselect("input[type='number']")
    assert row("IT.CM.CMDOSE").cssselect("input[type='number']")
    assert row("IT.AE.AESEV").cssselect("select option")[1].text == "Mild"
    # two options are radios, each inside a label that keeps the decode libxslt used to drop
    radios = row("IT.AE.AESER").cssselect("label.option")
    assert [r.cssselect("input[type='radio']")[0].get("value") for r in radios] == ["N", "Y"]
    assert [r.cssselect(".decode")[0].text for r in radios] == ["No", "Yes"]
    assert "maxlength" not in etree.tostring(row("IT.VS.SYSBPU")).decode()


def test_select_has_no_id(render):
    doc = render(SYNTHETIC)
    assert all(select.get("id") is None for select in doc.cssselect("select"))


def test_print_mode_has_static_controls(render):
    doc = render(SYNTHETIC, mode="print")

    assert not doc.cssselect("input") and not doc.cssselect("select") and not doc.cssselect("style")
    assert doc.cssselect("body")[0].get("class") == "mode-print"
    sev = doc.cssselect("tr.item[data-item-oid='IT.AE.AESEV'] td.response label.option")
    assert [o.cssselect(".decode")[0].text for o in sev] == ["Mild", "Moderate", "Severe"]
    assert all(o.cssselect("span.box") for o in sev)
    assert doc.cssselect("tr.item[data-item-oid='IT.VS.VSDTC'] span.field.date")[0].text == "DD / MMM / YYYY"


@pytest.fixture
def long_codelist(edited_crf) -> Path:
    """the synthetic CRF with 25 severity terms, each annotated, so the print cap applies to an annotated codelist"""
    def edit(tree):
        mdv = tree.getroot().find(".//odm:MetaDataVersion", NS)
        codelist = [c for c in mdv.findall("odm:CodeList", NS) if c.get("OID") == "CL.AESEV"][0]
        template = codelist.find("odm:CodeListItem", NS)
        for n in range(22):
            item = etree.fromstring(etree.tostring(template))
            item.set("CodedValue", f"GRADE{n}")
            etree.SubElement(item, _odm.tag("Alias"), Context="SDTM", Name=f"AE.AESEV=GRADE{n}")
            codelist.append(item)

    return edited_crf(edit)


def test_print_mode_caps_long_codelists_but_keeps_their_annotations(long_codelist, render):
    doc = render(long_codelist, mode="print")
    cell = doc.cssselect("tr.item[data-item-oid='IT.AE.AESEV'] td.response")[0]

    assert not cell.cssselect("label.option")
    assert cell.cssselect("span.field.text")
    assert cell.cssselect(".codelist-note")[0].text_content() == "Select from Severity (25 terms)"
    # the codelist item annotations move to the annotation column, so the data-* set is unchanged
    annos = doc.cssselect("tr.item[data-item-oid='IT.AE.AESEV'] td.anno-cell span.anno-codelist-item")
    assert len(annos) == 22
    # a higher cap lists them beside the options again, and the screen rendering is a select as before
    assert render(long_codelist, mode="print", codelist_items=25).cssselect(
        "tr.item[data-item-oid='IT.AE.AESEV'] td.response label.option span.anno")
    assert len(render(long_codelist).cssselect("tr.item[data-item-oid='IT.AE.AESEV'] select option")) == 26


def test_codelist_items_option_is_validated():
    with pytest.raises(CrfHtmlGenerationError, match="codelist items"):
        CrfHtml(SYNTHETIC, codelist_items=-1)


def test_print_mode_title_page(render):
    doc = render(SYNTHETIC, mode="print", title_page=True, title="Annotated CRF - SYNTH", generated_on="2026-10-17",
                 version="0.1.0")

    assert doc.findtext(".//title") == "Annotated CRF - SYNTH"
    page = doc.cssselect("section.title-page")[0]
    assert page.cssselect("h1.doc-title")[0].text == "Annotated CRF - SYNTH"
    assert page.cssselect("span.doc-study")[0].text == "SYNTH"
    assert "SYNTH-001" in page.text_content() and "2026-10-17" in page.text_content()
    assert not doc.cssselect("header.doc-header")
    assert "crfutils 0.1.0 on 2026-10-17" in doc.cssselect("footer.doc-footer")[0].text_content()


def test_screen_mode_has_no_footer_or_title_page(render):
    doc = render(SYNTHETIC, title_page=True)
    assert not doc.cssselect("footer") and not doc.cssselect("section.title-page")


# annotations

def test_annotation_spans_carry_the_contract(render):
    doc = render(SYNTHETIC)
    spans = doc.cssselect("span.anno")

    assert spans
    for span in spans:
        assert span.get("data-level") in ("form", "section", "concept", "item", "codelist-item")
        assert span.get("data-source") in ("alias:SDTM", "alias:formAnnotation", "alias:formSectionAnnotation",
                                           "attr:Domain")
        assert span.get("data-text") == span.text_content()
        assert span.get("data-form-oid") and span.get("data-group-path")
        assert ("anno-" + span.get("data-level")) in span.get("class").split()
    item = [s for s in spans if s.get("data-item-oid") == "IT.VS.SYSBPU"][0]
    assert item.get("data-text") == "VSORRESU = mmHg when VSTESTCD = SYSBP"
    assert item.get("data-group-path") == "IG.FORM.VS > IG.SEC.VS > IG.CON.SYSBP"
    cli = [s for s in spans if s.get("data-level") == "codelist-item"]
    assert {(s.get("data-codelist-oid"), s.get("data-coded-value"), s.get("data-text")) for s in cli} == \
           {("CL.SEX", "M", "DM.SEX=M"), ("CL.SEX", "F", "DM.SEX=F")}


def test_form_level_annotations_by_vocabulary(render):
    doc = render(SYNTHETIC)
    by_form = {f.get("data-form-oid"): [(s.get("data-source"), s.text) for s in f.cssselect(".form-annotations span.anno")]
               for f in _forms(doc)}

    assert by_form["IG.FORM.VS"] == [("alias:formAnnotation", "DOMAIN = VS")]
    assert by_form["IG.FORM.DM"] == [("alias:SDTM", "DM")]
    assert by_form["IG.FORM.CM"] == [("attr:Domain", "CM")]
    assert by_form["IG.FORM.AE/1"] == []


def test_codelist_item_annotations_sit_in_the_annotation_column_on_screen_and_beside_the_option_in_print(render):
    screen = render(SYNTHETIC)
    cell = screen.cssselect("tr.item[data-item-oid='IT.DM.SEX'] td.anno-cell")[0]
    assert [" ".join(d.text_content().split()) for d in cell.cssselect(".option-anno")] == ["M: DM.SEX=M", "F: DM.SEX=F"]

    printed = render(SYNTHETIC, mode="print")
    options = printed.cssselect("tr.item[data-item-oid='IT.DM.SEX'] td.response label.option")
    assert [o.cssselect("span.anno")[0].text for o in options] == ["DM.SEX=M", "DM.SEX=F"]
    assert not printed.cssselect("tr.item[data-item-oid='IT.DM.SEX'] td.anno-cell .option-anno")


def test_blank_crf_has_no_annotations(render):
    doc = render(SYNTHETIC, annotations=False)

    assert not doc.cssselect("span.anno") and not doc.cssselect("th.col-anno") and not doc.cssselect("td.anno-cell")
    assert doc.cssselect("tr.group-head td.group-name")[0].get("colspan") == "3"


def test_types_option(render):
    assert not render(SYNTHETIC).cssselect("div.type")
    types = {row.get("data-item-oid"): row.cssselect("div.type")[0].text_content().strip()
             for row in render(SYNTHETIC, types=True).cssselect("tr.item")}
    assert types["IT.AE.AETERM"] == "text (200)" and types["IT.VS.VSDTC"] == "date"


# ids and links

@pytest.mark.parametrize("name", FIXTURES)
def test_ids_are_unique_safe_and_every_link_resolves(name, render):
    doc = render(fixture_path(name))
    ids = [e.get("id") for e in doc.iter() if e.get("id") is not None]

    assert len(ids) == len(set(ids))
    assert all(ID.match(i) for i in ids)
    forms = [e.get("id") for e in _forms(doc)]
    assert forms and all(i.startswith("F.") for i in forms)
    annos = [e.get("id") for e in doc.cssselect("span.anno")]
    assert annos == [f"A.{n}" for n in range(1, len(annos) + 1)]
    assert set(ids) == set(forms) | set(annos)
    for link in doc.cssselect("a"):
        href = link.get("href")
        assert href is not None and href.startswith("#") and href[1:] in ids


def test_form_id_is_the_sanitized_oid(render):
    doc = render(SYNTHETIC)
    renderer = CrfHtml(SYNTHETIC)
    renderer.transform_to_html_string()

    assert {f.get("data-form-oid"): f.get("id") for f in _forms(doc)} == \
           {"IG.FORM.DM": "F.IG.FORM.DM", "IG.FORM.VS": "F.IG.FORM.VS", "IG.FORM.CM": "F.IG.FORM.CM",
            "IG.FORM.AE/1": "F.IG.FORM.AE_1"}
    assert renderer.form_ids["IG.FORM.AE/1"] == "F.IG.FORM.AE_1"
    assert sanitize_id("a b/c:d.e-f_g") == "a_b_c_d.e-f_g"


def test_colliding_form_ids_get_a_suffix(edited_crf, render):
    def edit(tree):
        mdv = tree.getroot().find(".//odm:MetaDataVersion", NS)
        form = [g for g in mdv.findall("odm:ItemGroupDef", NS) if g.get("OID") == "IG.FORM.AE/1"][0]
        clone = etree.fromstring(etree.tostring(form))
        clone.set("OID", "IG.FORM.AE_1")
        form.addnext(clone)

    doc = render(edited_crf(edit))
    ids = {f.get("data-form-oid"): f.get("id") for f in _forms(doc)}
    assert ids["IG.FORM.AE/1"] == "F.IG.FORM.AE_1" and ids["IG.FORM.AE_1"] == "F.IG.FORM.AE_1-2"
    for link in doc.cssselect("a.toc-link"):
        assert link.get("href") == "#" + ids[link.get("data-form-oid")]


# toc and visit matrix

def test_toc_and_matrix(render):
    doc = render(SYNTHETIC)
    toc = [a.text for a in doc.cssselect("nav.toc a.toc-link")]
    assert toc == ["Demographics", "Vital Signs", "Concomitant Medications", "Adverse Events"]
    matrix = doc.cssselect("section.visit-matrix table.matrix")[0]
    assert [th.text for th in matrix.cssselect("thead th.matrix-visit")] == ["Screening", "Week 1", "Common"]
    cells = {row.cssselect("a.matrix-link")[0].get("data-form-oid"): [td.text for td in row.cssselect("td.matrix-cell")]
             for row in matrix.cssselect("tbody tr")}
    assert cells["IG.FORM.VS"] == ["X", "X", None]
    assert cells["IG.FORM.CM"] == [None, "(X)", "(X)"]
    assert cells["IG.FORM.AE/1"] == [None, None, None]


def test_toc_and_matrix_options(render):
    doc = render(SYNTHETIC, toc=False, visit_matrix=False)
    assert not doc.cssselect("nav.toc") and not doc.cssselect("section.visit-matrix")


def test_single_form_has_no_toc_and_no_schedule_has_no_matrix(render):
    doc = render(fixture_path("vital_signs_odmv2-0.xml"))
    assert not doc.cssselect("nav.toc") and not doc.cssselect("section.visit-matrix")
    atlas = render(fixture_path("Atlas_QS_ODMv2.xml"))
    assert not atlas.cssselect("nav.toc") and atlas.cssselect("section.visit-matrix")


# the stylesheet, defects and missing definitions

def test_radio_labels_are_rendered_under_libxslt(render):
    # defect 1 of the original stylesheet: the decode was emitted inside the void <input>
    doc = render(fixture_path("vital_signs_odmv2-0.xml"))
    labels = doc.cssselect("label.option")
    assert labels and all(label.cssselect(".decode")[0].text for label in labels)


def test_missing_definitions_render_a_marker_not_an_error(edited_crf, render):
    def edit(tree):
        mdv = tree.getroot().find(".//odm:MetaDataVersion", NS)
        form = [g for g in mdv.findall("odm:ItemGroupDef", NS) if g.get("OID") == "IG.FORM.AE/1"][0]
        form.find("odm:ItemGroupRef", NS).set("ItemGroupOID", "IG.NOPE")
        section = [g for g in mdv.findall("odm:ItemGroupDef", NS) if g.get("OID") == "IG.SEC.DM"][0]
        section.find("odm:ItemRef", NS).set("ItemOID", "IT.NOPE")
        [d for d in mdv.findall("odm:ItemDef", NS) if d.get("OID") == "IT.DM.SEX"][0].find(
            "odm:CodeListRef", NS).set("CodeListOID", "CL.NOPE")

    doc = render(edited_crf(edit))
    assert "ItemGroupDef IG.NOPE is not defined" in doc.cssselect("tr.group-head.missing")[0].text_content()
    assert "ItemDef IT.NOPE is not defined" in doc.cssselect("tr.item[data-item-oid='IT.NOPE']")[0].text_content()
    assert "CodeList CL.NOPE is not defined" in doc.cssselect("tr.item[data-item-oid='IT.DM.SEX']")[0].text_content()


def test_cycle_renders_one_marker_row(edited_crf, render):
    def edit(tree):
        mdv = tree.getroot().find(".//odm:MetaDataVersion", NS)
        concept = [g for g in mdv.findall("odm:ItemGroupDef", NS) if g.get("OID") == "IG.CON.SYSBP"][0]
        concept.append(etree.SubElement(concept, _odm.tag("ItemGroupRef"), ItemGroupOID="IG.SEC.VS", Mandatory="No"))

    path = edited_crf(edit)
    doc = render(path)
    vs = [f for f in _forms(doc) if f.get("data-form-oid") == "IG.FORM.VS"][0]
    cycle = vs.cssselect("tr.group-head.cycle")
    assert len(cycle) == 1 and "contains itself" in cycle[0].text_content()
    assert len(_rows(vs)) == len(_design(path).walk("IG.FORM.VS"))


# refusals

def test_odm_v1_3_is_refused(tmp_path):
    crf = tmp_path / "odm13.xml"
    crf.write_text('<ODM xmlns="http://www.cdisc.org/ns/odm/v1.3" FileOID="F" FileType="Snapshot" '
                   'CreationDateTime="2026-01-01T00:00:00" ODMVersion="1.3.2"/>', encoding="utf-8")

    with pytest.raises(CrfHtmlGenerationError, match="an ODM v1.3 document") as excinfo:
        CrfHtml(crf).transform_to_html_string()
    assert "No HTML was generated" in str(excinfo.value)


def test_no_forms_is_refused(edited_crf):
    def edit(tree):
        for group in tree.getroot().findall(".//odm:ItemGroupDef", NS):
            group.set("Type", "Section")

    with pytest.raises(CrfHtmlGenerationError, match="no ItemGroupDef with Type='Form'"):
        CrfHtml(edited_crf(edit)).transform_to_html_string()


def test_missing_file_is_refused(tmp_path):
    with pytest.raises(CrfHtmlGenerationError, match="not found"):
        CrfHtml(tmp_path / "nope.xml")


def test_malformed_file_is_refused(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("<ODM><broken></ODM>", encoding="utf-8")
    with pytest.raises(CrfHtmlGenerationError, match="not well-formed XML"):
        CrfHtml(bad).transform_to_html_string()


def test_bad_options_are_refused():
    with pytest.raises(CrfHtmlGenerationError, match="mode"):
        CrfHtml(SYNTHETIC, mode="pdf")
    with pytest.raises(CrfHtmlGenerationError, match="annotations"):
        CrfHtml(SYNTHETIC, annotations="1")


def test_output_that_is_the_input_is_refused(tmp_path):
    crf = tmp_path / "crf.xml"
    crf.write_bytes(SYNTHETIC.read_bytes())
    with pytest.raises(CrfHtmlWriteError, match="is the input file"):
        CrfHtml(crf).transform_to_html_file(crf)
    assert etree.parse(str(crf)).getroot().tag == _odm.tag("ODM")


def test_output_folder_is_refused(tmp_path):
    with pytest.raises(CrfHtmlWriteError, match="write to a directory"):
        CrfHtml(SYNTHETIC).transform_to_html_file(tmp_path)
    with pytest.raises(CrfHtmlWriteError, match="does not exist"):
        CrfHtml(SYNTHETIC).transform_to_html_file(tmp_path / "missing" / "crf.html")


def test_write_error_is_a_generation_error():
    assert issubclass(CrfHtmlWriteError, CrfHtmlGenerationError)


def test_transform_error_quotes_the_stylesheet_log(tmp_path, monkeypatch):
    broken = tmp_path / "broken.xsl"
    broken.write_text("""<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0">
<xsl:template match="/"><xsl:message terminate="yes">deliberate failure</xsl:message></xsl:template>
</xsl:stylesheet>""", encoding="utf-8")
    import crfutils.crfhtml.crfhtml as module
    monkeypatch.setattr(module, "STYLESHEET", broken)

    with pytest.raises(CrfHtmlGenerationError, match="The stylesheet failed") as excinfo:
        CrfHtml(SYNTHETIC).transform_to_html_string()
    assert "deliberate failure" in str(excinfo.value)


def test_file_output_matches_the_string(tmp_path):
    out = tmp_path / "crf.html"
    renderer = CrfHtml(SYNTHETIC)
    renderer.transform_to_html_file(out)

    assert out.read_bytes().decode("utf-8") == renderer.transform_to_html_string()
    assert renderer.transform_to_tree() is renderer.transform_to_tree()


def test_oid_with_whitespace_falls_back_to_document_order(edited_crf):
    def edit(tree):
        mdv = tree.getroot().find(".//odm:MetaDataVersion", NS)
        for e in mdv.iter():
            for attr in ("OID", "ItemGroupOID"):
                if e.get(attr) == "IG.FORM.DM":
                    e.set(attr, "IG FORM DM")

    renderer = CrfHtml(edited_crf(edit))
    doc = html.fromstring(renderer.transform_to_html_string())
    assert renderer.notes == ["a form OID contains whitespace; forms are rendered in document order"]
    assert [f.get("data-form-oid") for f in _forms(doc)] == ["IG.FORM.AE/1", "IG.FORM.VS", "IG FORM DM", "IG.FORM.CM"]
    assert [f.get("id") for f in _forms(doc)][2] == "F.IG_FORM_DM"


# the command

def test_cli_writes_beside_the_input_by_default(tmp_path, run_cli):
    crf = tmp_path / "crf.xml"
    crf.write_bytes(SYNTHETIC.read_bytes())

    completed = run_cli("crfhtml", "-c", str(crf))

    assert completed.returncode == 0
    assert (tmp_path / "crf.html").read_bytes().decode("utf-8") == CrfHtml(crf).transform_to_html_string()
    assert completed.stdout == b"" and completed.stderr == b""


def test_cli_options(tmp_path, run_cli):
    out = tmp_path / "blank.html"
    completed = run_cli("crfhtml", "-c", str(SYNTHETIC), "-o", str(out), "--blank", "--types", "--no-toc",
                        "--no-visit-matrix")

    assert completed.returncode == 0
    doc = html.fromstring(out.read_bytes())
    assert not doc.cssselect("span.anno") and doc.cssselect("div.type")
    assert not doc.cssselect("nav.toc") and not doc.cssselect("section.visit-matrix")


def test_cli_missing_file_exits_2(tmp_path, run_cli):
    completed = run_cli("crfhtml", "-c", str(tmp_path / "nope.xml"))

    assert completed.returncode == 2
    assert b"not found" in completed.stderr


def test_cli_output_folder_exits_2(tmp_path, run_cli):
    completed = run_cli("crfhtml", "-c", str(SYNTHETIC), "-o", str(tmp_path))

    assert completed.returncode == 2
    assert b"write to a directory" in completed.stderr


def test_main_exits_1_with_a_traceback_on_an_unexpected_error(monkeypatch, capsys):
    import crfutils.crfhtml.__main__ as cli

    def crash(*args, **kwargs):
        raise RuntimeError("simulated defect")

    monkeypatch.setattr(cli, "CrfHtml", crash)
    monkeypatch.setattr(sys, "argv", ["crfhtml", "-c", str(SYNTHETIC)])

    assert cli.main() == 1
    assert "RuntimeError: simulated defect" in capsys.readouterr().err


def test_stylesheet_license_is_bundled():
    assert STYLESHEET.with_name("odm_2-0_crf.xsl.LICENSE").is_file()
    assert (Path(__file__).parent.parent / "stylesheet_changes.md").is_file()
