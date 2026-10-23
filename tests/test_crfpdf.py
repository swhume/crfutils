"""
crfpdf: the annotated CRF PDF checked with pypdf -- bookmarks, page mode, title, named destinations, fonts, page
size, footers, the annotation pages recorded in the JSON -- and the page-references JSON itself. Skipped when
WeasyPrint (or the Pango it needs) is not installed.
"""
import io
import json
import re
from pathlib import Path

import pytest
from lxml import html

from conftest import SYNTHETIC, fixture_path
from crfutils import __version__
from crfutils.crfpdf import CrfPdf, CrfPdfError, CrfPdfWriteError, KEY_FORMAT, SCHEMA_VERSION

pytestmark = pytest.mark.usefixtures("weasyprint_required")

LETTER = (612, 792)
A4 = (595, 842)


@pytest.fixture(scope="module")
def rendered():
    pdf = CrfPdf(SYNTHETIC)
    return pdf, pdf.render()


@pytest.fixture(scope="module")
def reader(rendered):
    import pypdf
    return pypdf.PdfReader(io.BytesIO(rendered[1].pdf_bytes))


def _outline(reader) -> list:
    """(depth, title, page number) for every bookmark"""
    out = []

    def walk(items, depth):
        for item in items:
            if isinstance(item, list):
                walk(item, depth + 1)
            else:
                out.append((depth, item.title, reader.get_destination_page_number(item) + 1))

    walk(reader.outline, 0)
    return out


def _fonts(reader) -> dict:
    """base font name -> whether a font program is embedded"""
    fonts = {}
    for page in reader.pages:
        for font in (page.get("/Resources", {}).get("/Font") or {}).values():
            font = font.get_object()
            descriptor = font.get("/FontDescriptor")
            if descriptor is None and font.get("/DescendantFonts"):
                descriptor = font["/DescendantFonts"][0].get_object().get("/FontDescriptor")
            descriptor = descriptor.get_object() if descriptor is not None else {}
            embedded = any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3"))
            fonts[str(font.get("/BaseFont"))] = embedded
    return fonts


# the PDF

def test_page_count_forms_and_order(rendered, reader):
    pdf, result = rendered
    assert result.page_count == len(reader.pages) > 4
    assert [f.oid for f in result.forms] == ["IG.FORM.DM", "IG.FORM.VS", "IG.FORM.CM", "IG.FORM.AE/1"]
    firsts = [f.first_page for f in result.forms]
    assert firsts == sorted(firsts)
    for form, following in zip(result.forms, result.forms[1:]):
        assert form.last_page == following.first_page - 1
    assert result.forms[-1].last_page == result.page_count
    assert result.forms[0].first_page == 4          # title page, TOC, visit matrix, then the first form


def test_bookmarks(reader, rendered):
    outline = _outline(reader)
    titles = [title for _, title, _ in outline]
    assert titles[:3] == ["Table of Contents", "Visit Matrix", "Forms"]
    forms = {f.name: f.first_page for f in rendered[1].forms}
    for depth, title, page in outline:
        if depth == 1 and title in forms:
            assert page == forms[title]
    assert (0, "Visits", rendered[1].forms[0].first_page) in outline
    assert (1, "Screening", forms["Demographics"]) in outline
    assert (2, "Concomitant Medications (optional)", forms["Concomitant Medications"]) in outline
    assert (1, "Common", forms["Concomitant Medications"]) in outline
    assert (0, "Table of Contents", 2) in outline and (0, "Visit Matrix", 3) in outline


def test_viewer_settings(reader):
    assert reader.page_mode == "/UseOutlines"
    assert bool(reader.viewer_preferences.display_doctitle) is True
    assert reader.metadata.title == "Annotated CRF - SYNTH"
    assert reader.metadata.author == "crfutils tests"
    assert f"crfpdf {__version__}" in str(reader.metadata.producer or "") + str(reader.metadata.creator or "")


def test_named_destinations_are_exactly_the_forms(reader, rendered):
    assert set(reader.named_destinations) == {f.named_destination for f in rendered[1].forms} == \
           {"F.IG.FORM.DM", "F.IG.FORM.VS", "F.IG.FORM.CM", "F.IG.FORM.AE_1"}
    for form in rendered[1].forms:
        assert reader.get_destination_page_number(reader.named_destinations[form.named_destination]) + 1 == form.first_page


def test_fonts_are_embedded_and_bundled(reader):
    fonts = _fonts(reader)
    assert fonts and all(fonts.values()), fonts
    assert all("CRFUtils-Sans" in name for name in fonts), fonts


def test_no_encryption_and_pdf_1_7(reader, rendered):
    assert not reader.is_encrypted
    assert reader.trailer.get("/Encrypt") is None
    assert rendered[1].pdf_bytes.startswith(b"%PDF-1.7")


def test_page_size_letter_and_landscape_matrix(reader):
    width, height = reader.pages[0].mediabox.width, reader.pages[0].mediabox.height
    assert (round(width), round(height)) == LETTER
    assert (round(reader.pages[2].mediabox.width), round(reader.pages[2].mediabox.height)) == (LETTER[1], LETTER[0])


def test_a4():
    pdf = CrfPdf(SYNTHETIC, page_size="a4", visit_bookmarks=False)
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(pdf.render().pdf_bytes))
    assert (round(reader.pages[0].mediabox.width), round(reader.pages[0].mediabox.height)) == A4
    assert "Visits" not in [title for _, title, _ in _outline(reader)]


def test_footer_page_numbers_and_running_strings(reader):
    count = len(reader.pages)
    for number, page in enumerate(reader.pages, 1):
        text = page.extract_text()
        assert f"Page {number} of {count}" in text
        if number > 1:
            assert "SYNTH" in text
    assert "Vital Signs" in reader.pages[4].extract_text().split("\n")[0]       # the running header names the form


def test_title_page_and_toc(reader):
    first = reader.pages[0].extract_text()
    assert "Annotated CRF - SYNTH" in first and "SYNTH-001" in first and "Synthetic CRF metadata" in first
    toc = reader.pages[1].extract_text()
    assert "Table of Contents" in toc
    assert re.search(r"Demographics\s*\.+\s*4", toc)


def test_every_annotation_is_on_a_recorded_page(reader, rendered):
    result = rendered[1]
    assert result.annotations and all(a.page is not None for a in result.annotations)
    for entry in result.refs["annotations"]:
        assert entry["pages"]
        for page in entry["pages"]:
            assert entry["text"] in reader.pages[page - 1].extract_text().replace("\n", " ")
    assert not [w for w in result.warnings if w.check == "annotation_not_paginated"]


def test_annotations_are_coloured_by_domain(rendered):
    doc = html.fromstring(rendered[1].html)
    indexes = {span.get("data-text"): span.get("data-domain-index") for span in doc.cssselect("span.anno")}
    assert indexes["DM"] == "1" and indexes["SEX"] == "1"
    assert indexes["CMINDC in SUPPCM"] != indexes["CMTRT"]      # SUPPCM is a second domain on the CM form
    assert indexes["see protocol section 5"] == "0"
    assert indexes["[NOT SUBMITTED]"] == "0"
    assert "CRFUtils Sans" in rendered[1].html and "@font-face" in rendered[1].html
    assert doc.cssselect("meta[name='generator']")[0].get("content") == f"crfutils crfpdf {__version__}"


# the page-references JSON

def test_json_structure(rendered):
    refs = rendered[1].refs
    assert set(refs) == {"schema_version", "key_format", "generator", "generated", "crf_file", "pdf_file", "pdf_sha256",
                         "page_count", "page_size", "study", "leaf", "forms", "visits", "annotations", "index",
                         "origins", "domains", "warnings"}
    assert refs["schema_version"] == SCHEMA_VERSION == "2.0"
    assert refs["key_format"] == KEY_FORMAT
    assert refs["generator"]["name"] == "crfpdf" and refs["generator"]["version"] == __version__
    assert refs["generator"]["weasyprint"] == rendered[1].weasyprint_version
    assert refs["study"] == {"oid": "ST.SYNTH", "name": "SYNTH", "protocol": "SYNTH-001", "mdv_oid": "MDV.1"}
    assert refs["leaf"] == {"id": "LF.acrf", "href": "acrf.pdf", "title": "Annotated CRF"}
    assert refs["page_size"] == "letter" and refs["page_count"] == rendered[1].page_count
    assert len(refs["pdf_sha256"]) == 64
    assert [v["oid"] for v in refs["visits"]] == ["SE.SCR", "SE.WK1", "SE.COMMON"]
    assert refs["visits"][0]["forms"] == ["IG.FORM.DM", "IG.FORM.VS"]
    assert refs["pdf_file"].endswith("crf_synthetic_acrf.pdf")


def test_json_forms(rendered):
    forms = {f["oid"]: f for f in rendered[1].refs["forms"]}
    assert forms["IG.FORM.VS"]["domains"] == ["VS"] and forms["IG.FORM.VS"]["visits"] == ["SE.SCR", "SE.WK1"]
    assert forms["IG.FORM.CM"]["domains"] == ["CM"]
    assert forms["IG.FORM.AE/1"]["visits"] == [] and forms["IG.FORM.AE/1"]["named_destination"] == "F.IG.FORM.AE_1"
    assert set(forms["IG.FORM.DM"]) == {"oid", "name", "domains", "named_destination", "first_page", "last_page", "visits"}


def test_json_annotations_and_index(rendered):
    refs = rendered[1].refs
    by_text = {a["text"]: a for a in refs["annotations"]}
    sysbpu = by_text["VSORRESU = mmHg when VSTESTCD = SYSBP"]
    assert sysbpu["level"] == "item" and sysbpu["item_oid"] == "IT.VS.SYSBPU" and sysbpu["item_name"] == "SYSBPU"
    assert sysbpu["group_path"] == ["IG.FORM.VS", "IG.SEC.VS", "IG.CON.SYSBP"]
    assert sysbpu["status"] == "parsed" and sysbpu["not_submitted"] is False and sysbpu["occurrences"] == 1
    # the concept group's prefilled VSLOC = ARM is added to the annotation's own condition
    target = sysbpu["targets"][0]
    assert target == {"dataset": "VS", "dataset_source": "prefix", "variable": "VSORRESU",
                      "variable_source": "annotation", "value": "mmHg",
                      "where": [{"variable": "VSTESTCD", "comparator": "EQ", "values": ["SYSBP"], "source": "annotation"},
                                {"variable": "VSLOC", "comparator": "EQ", "values": ["ARM"], "source": "concept"}],
                      "qnam": None, "key": "VS.VSORRESU where VSLOC = ARM and VSTESTCD = SYSBP"}
    # the evidence for the origin: the ItemRef, the item's mapping instructions, and what was proposed from them
    assert sysbpu["item_origins"] == [{"type": "Protocol", "source": "Sponsor"}]
    assert sysbpu["prespecified_value"] == "mmHg" and sysbpu["mapping_instructions"] is None
    assert sysbpu["proposed_origin"] == {"type": "Protocol", "source": "Sponsor", "basis": "ItemRef/Origin",
                                         "description": None}
    vs_pages = [f for f in refs["forms"] if f["oid"] == "IG.FORM.VS"][0]
    assert all(vs_pages["first_page"] <= p <= vs_pages["last_page"] for p in sysbpu["pages"])
    # the index holds every key, the key without the concept conditions, and the variable-level roll-up
    for key in ("VS.VSORRESU where VSLOC = ARM and VSTESTCD = SYSBP", "VS.VSORRESU where VSTESTCD = SYSBP", "VS.VSORRESU"):
        assert refs["index"][key] == sysbpu["pages"], key
    # an SDTM alias that disagrees with the mapping instructions is corrected to the variable they name
    aeendat = by_text["AEENDAT"]
    assert [(t["key"], t["variable_source"]) for t in aeendat["targets"]] == [("AE.AEENDTC", "mappingInstructions")]
    assert aeendat["mapping_instructions"]["kind"] == "concatenated"
    assert aeendat["mapping_instructions"]["variables"] == ["AEENDTC"]
    assert "AE.AEENDAT" not in refs["index"]
    assert by_text["AETERM"]["item_origins"] == [{"type": "Collected", "source": "Investigator"}]
    assert by_text["AESER"]["item_origins"] == [] and by_text["AESER"]["prespecified_value"] is None
    form = [a for a in refs["annotations"] if a["level"] == "form"][0]
    assert (form["item_origins"], form["prespecified_value"], form["mapping_instructions"], form["proposed_origin"]) == \
           ([], None, None, None)
    assert refs["index"]["SUPPCM.QVAL where QNAM = CMINDC"] == by_text["CMINDC in SUPPCM"]["pages"]
    assert refs["index"]["DM.SEX"] == by_text["SEX"]["pages"]
    sex_m = by_text["DM.SEX=M"]
    assert sex_m["level"] == "codelist-item" and sex_m["coded_value"] == "M" and sex_m["codelist_oid"] == "CL.SEX"
    assert by_text["[NOT SUBMITTED]"]["not_submitted"] is True and by_text["[NOT SUBMITTED]"]["targets"] == []
    assert by_text["CMDOSE;CMDOSTXT"]["targets"][1]["key"] == "CM.CMDOSTXT"
    dm = [a for a in refs["annotations"] if a["text"] == "DM"]
    assert [a["level"] for a in dm] == ["form", "section"] and dm[0]["domains"] == ["DM"]
    assert dm[0]["source"] == "alias:SDTM" and dm[1]["source"] == "attr:Domain"


def test_json_domains_and_warnings(rendered):
    refs = rendered[1].refs
    forms = {f["oid"]: f for f in refs["forms"]}
    assert refs["domains"]["VS"] == list(range(forms["IG.FORM.VS"]["first_page"], forms["IG.FORM.VS"]["last_page"] + 1))
    assert "SUPPCM" in refs["domains"]
    assert refs["warnings"] == [
        {"check": "unparsed_annotation", "text": "see protocol section 5", "form_oid": "IG.FORM.DM",
         "item_oid": "IT.DM.NOTE"},
        {"check": "sdtm_alias_disagrees", "text": "the SDTM annotation names AEENDAT; the mapping instructions name AEENDTC",
         "form_oid": "IG.FORM.AE/1", "item_oid": "IT.AE.AEENDAT"}]


def test_json_origins(rendered):
    refs = rendered[1].refs
    origins = refs["origins"]
    pages = {a["item_oid"]: a["pages"] for a in refs["annotations"] if a["level"] == "item"}

    def only(key: str) -> dict:
        assert len(origins[key]) == 1, origins[key]
        return origins[key][0]

    assert set(origins) == set(refs["index"])
    # the ItemRef's Origin, with the prefilled value
    assert only("VS.VSORRESU where VSLOC = ARM and VSTESTCD = SYSBP") == {
        "type": "Protocol", "source": "Sponsor", "description": None, "basis": ["ItemRef/Origin"], "mapping": [],
        "values": ["mmHg"], "items": ["IT.VS.SYSBPU"], "pages": pages["IT.VS.SYSBPU"]}
    assert only("VS.VSLOC")["values"] == ["ARM"]
    aeterm = only("AE.AETERM")
    assert (aeterm["type"], aeterm["source"], aeterm["mapping"]) == ("Collected", "Investigator", ["direct"])
    # date and time concatenated into --DTC stay collected; with no ItemRef Origin the source is a placeholder
    aeendtc = only("AE.AEENDTC")
    assert (aeendtc["type"], aeendtc["source"], aeendtc["basis"], aeendtc["mapping"], aeendtc["pages"]) == \
           ("Collected", "__PLACEHOLDER__", ["annotation"], ["concatenated"], pages["IT.AE.AEENDAT"])
    # a field that feeds its targets indirectly proposes Derived, with the pages it is collected on
    for key, item, basis, mapping in (("CM.CMSTRF", "IT.CM.CMSTRF", "mappingInstructions", ["relative_timing"]),
                                      ("CM.CMSTRTPT", "IT.CM.CMSTRF", "mappingInstructions", ["relative_timing"]),
                                      ("CM.CMDOSTXT", "IT.CM.CMDOSE", "mappingInstructions", ["split"]),
                                      ("VS.VSSTAT where VSTESTCD = VSALL", "IT.VS.VSPERF", "not_submitted", [])):
        derived = only(key)
        assert (derived["type"], derived["source"], derived["description"], derived["basis"], derived["mapping"]) == \
               ("Derived", "Sponsor", "__PLACEHOLDER__", [basis], mapping), key
        assert derived["items"] == [item] and derived["pages"] == pages[item]
    # the codelist items' values are the variable's values
    assert only("DM.SEX")["values"] == ["M", "F"] and only("DM.SEX")["items"] == ["IT.DM.SEX"]


def test_result_file_renders_with_visits():
    pdf = CrfPdf(fixture_path("Result_ODMv2.xml"))
    result = pdf.render()
    assert len(result.forms) == 7 and result.page_count > 8
    assert [v["oid"] for v in result.refs["visits"]] == ["BASELINE", "WEEK_1", "WEEK_2", "DIARY", "AE"]
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(result.pdf_bytes))
    assert "Visits" in [title for _, title, _ in _outline(reader)]


def test_file_without_schedule_has_no_matrix_or_visits():
    result = CrfPdf(fixture_path("vital_signs_odmv2-0.xml")).render()
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(result.pdf_bytes))
    titles = [title for _, title, _ in _outline(reader)]
    assert "Visits" not in titles and "Visit Matrix" not in titles and "Table of Contents" not in titles
    assert result.forms[0].first_page == 2
    assert result.refs["visits"] == []


# writing

def test_write_defaults(tmp_path):
    crf = tmp_path / "study.xml"
    crf.write_bytes(SYNTHETIC.read_bytes())
    pdf = CrfPdf(crf)

    written = pdf.write()

    assert written == {"pdf": tmp_path / "study_acrf.pdf", "refs": tmp_path / "study_acrf.pagerefs.json"}
    assert (tmp_path / "study_acrf.pdf").read_bytes() == pdf.render().pdf_bytes
    refs = json.loads((tmp_path / "study_acrf.pagerefs.json").read_text(encoding="utf-8"))
    assert refs["pdf_file"] == str(tmp_path / "study_acrf.pdf")
    assert not (tmp_path / "acrf.pdf").exists()


def test_write_named_outputs(tmp_path):
    written = CrfPdf(SYNTHETIC).write(pdf_file=tmp_path / "acrf.pdf", refs_file=tmp_path / "refs.json",
                                      html_file=tmp_path / "acrf.html")
    assert set(written) == {"pdf", "refs", "html"}
    assert (tmp_path / "acrf.pdf").stat().st_size > 10000
    assert json.loads((tmp_path / "refs.json").read_text(encoding="utf-8"))["pdf_file"] == str(tmp_path / "acrf.pdf")
    doc = html.fromstring((tmp_path / "acrf.html").read_bytes())
    assert doc.cssselect("section.form")[0].get("id") == "F.IG.FORM.DM"
    assert doc.cssselect("span.anno")[0].get("data-domain-index") is not None


def test_write_refuses_bad_destinations(tmp_path):
    with pytest.raises(CrfPdfWriteError, match="write to a directory"):
        CrfPdf(SYNTHETIC).write(pdf_file=tmp_path)
    with pytest.raises(CrfPdfWriteError, match="is the input file"):
        CrfPdf(SYNTHETIC).write(pdf_file=SYNTHETIC)
    with pytest.raises(CrfPdfWriteError, match="does not exist"):
        CrfPdf(SYNTHETIC).write(pdf_file=tmp_path / "missing" / "acrf.pdf")
    assert not list(tmp_path.iterdir())


# refusals

def test_bad_page_size():
    with pytest.raises(CrfPdfError, match="page size"):
        CrfPdf(SYNTHETIC, page_size="legal")


def test_missing_file(tmp_path):
    with pytest.raises(CrfPdfError, match="not found"):
        CrfPdf(tmp_path / "nope.xml")


def test_v1_3_is_refused(tmp_path):
    crf = tmp_path / "odm13.xml"
    crf.write_text('<ODM xmlns="http://www.cdisc.org/ns/odm/v1.3" FileOID="F" FileType="Snapshot" '
                   'CreationDateTime="2026-01-01T00:00:00" ODMVersion="1.3.2"/>', encoding="utf-8")
    with pytest.raises(CrfPdfError, match="an ODM v1.3 document") as excinfo:
        CrfPdf(crf).render()
    assert "No PDF was generated" in str(excinfo.value)


def test_validate_option_refuses_an_invalid_file(edited_crf):
    def edit(tree):
        del tree.getroot().find(".//{http://www.cdisc.org/ns/odm/v2.0}ItemDef").attrib["DataType"]

    crf = edited_crf(edit)
    with pytest.raises(CrfPdfError, match="is not valid ODM v2.0") as excinfo:
        CrfPdf(crf, validate=True).render()
    assert f"crfvalidate -c {crf}" in str(excinfo.value)
    assert CrfPdf(SYNTHETIC, validate=True).render().page_count > 0


# the command

def test_cli(tmp_path, run_cli):
    completed = run_cli("crfpdf", "-c", str(SYNTHETIC), "-o", str(tmp_path / "acrf.pdf"), "--html", str(tmp_path / "a.html"),
                        "--title", "My CRF", "--page-size", "a4")

    assert completed.returncode == 0, completed.stderr
    out = completed.stdout.decode()
    assert out.startswith(f"Wrote {tmp_path / 'acrf.pdf'} (") and "4 forms, 3 visits" in out
    assert f"{tmp_path / 'acrf.pagerefs.json'} (" in out and "annotations)" in out
    assert f"Wrote {tmp_path / 'a.html'}" in out
    assert completed.stderr.decode() == (
        "2 warnings:\n  unparsed_annotation  IT.DM.NOTE: see protocol section 5\n"
        "  sdtm_alias_disagrees  IT.AE.AEENDAT: the SDTM annotation names AEENDAT; the mapping instructions name AEENDTC\n")
    import pypdf
    reader = pypdf.PdfReader(str(tmp_path / "acrf.pdf"))
    assert reader.metadata.title == "My CRF"
    assert (round(reader.pages[0].mediabox.width), round(reader.pages[0].mediabox.height)) == A4


def test_cli_exit_codes(tmp_path, run_cli):
    completed = run_cli("crfpdf", "-c", str(tmp_path / "nope.xml"))
    assert completed.returncode == 2 and b"not found" in completed.stderr
    completed = run_cli("crfpdf", "-c", str(SYNTHETIC), "-o", str(tmp_path))
    assert completed.returncode == 2 and b"write to a directory" in completed.stderr
    assert not list(tmp_path.iterdir())


def test_bundled_files_exist():
    from crfutils.crfpdf import CSS_FILE, FONT_DIR
    assert CSS_FILE.is_file()
    assert sorted(p.name for p in FONT_DIR.iterdir()) == ["LICENSE", "LiberationSans-Bold.ttf", "LiberationSans-BoldItalic.ttf",
                                                           "LiberationSans-Italic.ttf", "LiberationSans-Regular.ttf"]
    assert "SIL OPEN FONT LICENSE" in (FONT_DIR / "LICENSE").read_text(encoding="utf-8")
