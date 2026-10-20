"""_design: the study design read by lxml and by odmlib, the form and visit order, and the walk."""
import pytest
from lxml import etree

from conftest import FIXTURES, SYNTHETIC, fixture_path
from crfutils import _odm
from crfutils._design import MAX_DEPTH, ChildRef, StudyDesign, sort_key

NS = {"odm": _odm.ODM_NS}


def _design(path) -> StudyDesign:
    return StudyDesign(_odm.design_from_lxml(_odm.parse_odm(path, RuntimeError)))


def _model_design(path):
    from crfutils import _model
    odm, _ = _model.load_crf(path, RuntimeError, "Nothing was done", "re-run", "try again")
    return _model.design_from_model(odm)


@pytest.fixture(scope="module")
def synthetic() -> StudyDesign:
    return _design(SYNTHETIC)


# the two extractors agree

@pytest.mark.parametrize("name", FIXTURES)
def test_lxml_and_odmlib_read_the_same_design(name):
    from_lxml = _odm.design_from_lxml(_odm.parse_odm(fixture_path(name), RuntimeError))
    from_model = _model_design(fixture_path(name))

    assert from_lxml == from_model
    # dict equality ignores order, and document order matters for the rendering
    for field in ("groups", "items", "codelists", "events", "event_groups"):
        assert list(getattr(from_lxml, field)) == list(getattr(from_model, field)), field


# identity

def test_identity(synthetic):
    data = synthetic.data
    assert (data.study_oid, data.study_name, data.protocol_name) == ("ST.SYNTH", "SYNTH", "SYNTH-001")
    assert (data.mdv_oid, data.mdv_name) == ("MDV.1", "Synthetic CRF metadata")
    assert data.mdv_description == "Blank annotated CRFs covering the annotation vocabularies"
    assert data.acrf_leaf.id == "LF.acrf" and data.acrf_leaf.href == "acrf.pdf" and data.acrf_leaf.title == "Annotated CRF"


# visits and forms

def test_visit_order_follows_the_protocol_not_the_document(synthetic):
    assert synthetic.visits == ["SE.SCR", "SE.WK1", "SE.COMMON"]
    assert list(synthetic.data.events) == ["SE.WK1", "SE.SCR", "SE.COMMON"]


def test_form_order_follows_the_visits_then_the_unscheduled_forms(synthetic):
    assert synthetic.has_schedule
    assert synthetic.forms == ["IG.FORM.DM", "IG.FORM.VS", "IG.FORM.CM", "IG.FORM.AE/1"]
    assert synthetic.unscheduled_forms == ["IG.FORM.AE/1"]
    assert synthetic.events_without_forms == []
    assert synthetic.form_visits["IG.FORM.VS"] == ["SE.SCR", "SE.WK1"]
    assert synthetic.form_visits["IG.FORM.AE/1"] == []
    assert synthetic.mandatory("SE.WK1", "IG.FORM.CM") == "No"
    assert synthetic.mandatory("SE.SCR", "IG.FORM.CM") is None


def test_schedule_lists_forms_in_order_number_order(synthetic):
    assert [ref.oid for ref in synthetic.schedule["SE.SCR"]] == ["IG.FORM.DM", "IG.FORM.VS"]
    assert [ref.oid for ref in synthetic.schedule["SE.WK1"]] == ["IG.FORM.VS", "IG.FORM.CM"]


def test_no_schedule_keeps_document_order():
    design = _design(fixture_path("vital_signs_odmv2-0.xml"))

    assert not design.has_schedule
    assert design.visits == []
    assert design.forms == ["IG_FORM.VS1"]


def test_result_has_seven_forms_by_visit():
    design = _design(fixture_path("Result_ODMv2.xml"))

    assert design.visits == ["BASELINE", "WEEK_1", "WEEK_2", "DIARY", "AE"]
    assert design.forms == ["F_BASELINE", "F_CM", "F_LAB", "F_COMPLAINTS_REL_SMOKING", "F_WEEK_1_2", "F_DIARY", "F_AE"]
    assert sum(len(refs) for refs in design.schedule.values()) == 11


def test_unreached_events_are_appended_in_document_order(edited_crf):
    # an event the protocol does not reach goes after the scheduled ones
    def edit(tree):
        mdv = tree.getroot().find(".//odm:MetaDataVersion", NS)
        extra = etree.SubElement(mdv, _odm.tag("StudyEventDef"), OID="SE.EXTRA", Name="Extra", Repeating="No",
                                 Type="Unscheduled")
        mdv.find("odm:StudyEventDef", NS).addprevious(extra)

    design = _design(edited_crf(edit))
    assert design.visits == ["SE.SCR", "SE.WK1", "SE.COMMON", "SE.EXTRA"]
    assert "SE.EXTRA" in design.events_without_forms


# the walk

def test_sort_key_puts_children_without_order_number_first():
    children = [ChildRef("ItemRef", "b", 2, None), ChildRef("ItemRef", "n1", None, None),
                ChildRef("ItemRef", "a", 1, None), ChildRef("ItemRef", "n2", None, None)]
    assert [c.oid for c in sorted(children, key=sort_key)] == ["n1", "n2", "a", "b"]


def test_walk_keeps_document_order_without_order_numbers(synthetic):
    rows = [(row.kind, row.oid, row.depth) for row in synthetic.walk("IG.FORM.VS")]

    assert rows == [("group", "IG.SEC.VS", 1), ("item", "IT.VS.VSPERF", 1), ("group", "IG.CON.SYSBP", 2),
                    ("item", "IT.VS.SYSBP", 2), ("item", "IT.VS.SYSBPU", 2), ("item", "IT.VS.VSPOS", 2),
                    ("item", "IT.VS.VSDTC", 1)]
    assert [row.path for row in synthetic.walk("IG.FORM.VS")][3] == ("IG.FORM.VS", "IG.SEC.VS", "IG.CON.SYSBP")


def test_walk_sorts_by_order_number(synthetic):
    assert [row.oid for row in synthetic.items_on("IG.FORM.DM")] == \
           ["IT.DM.BRTHDTC", "IT.DM.SEX", "IT.DM.AGE", "IT.DM.AGEU", "IT.DM.NOTE"]
    assert [row.oid for row in synthetic.groups_on("IG.FORM.CM")] == ["IG.SEC.CM.TAKEN", "IG.SEC.CM"]


def test_walk_counts(synthetic):
    assert {form: len(synthetic.items_on(form)) for form in synthetic.forms} == \
           {"IG.FORM.DM": 5, "IG.FORM.VS": 5, "IG.FORM.CM": 6, "IG.FORM.AE/1": 4}


def test_mixed_children_in_columbia_follow_document_order():
    design = _design(fixture_path("Columbia-Suicide_Severity_Scale_ODMv2.xml"))
    rows = design.walk("FO.C-SSRS_Form")
    # 'Wish to be dead' group: an ItemGroupRef then an ItemRef, in document order
    kinds = [(row.kind, row.oid) for row in rows
             if (row.kind == "item" and row.path[-1] == "IG.Wish_to_bed_Dead_Group_with_Description")
             or row.oid == "IG.Wish_to_be_Dead"]
    assert kinds[0] == ("group", "IG.Wish_to_be_Dead")
    assert kinds[-1][0] == "item"


def test_cycle_is_recorded_and_not_entered(edited_crf):
    def edit(tree):
        mdv = tree.getroot().find(".//odm:MetaDataVersion", NS)
        concept = [g for g in mdv.findall("odm:ItemGroupDef", NS) if g.get("OID") == "IG.CON.SYSBP"][0]
        concept.append(etree.SubElement(concept, _odm.tag("ItemGroupRef"), ItemGroupOID="IG.SEC.VS", Mandatory="No"))

    design = _design(edited_crf(edit))
    rows = design.walk("IG.FORM.VS")

    assert design.cycles == [("IG.FORM.VS", "IG.SEC.VS", "IG.CON.SYSBP", "IG.SEC.VS")]
    assert len([row for row in rows if row.kind == "item"]) == 5
    # the repeated group gets its heading row (the stylesheet renders a marker there) but is not entered
    assert [(row.kind, row.oid) for row in rows].count(("group", "IG.SEC.VS")) == 2


def test_too_deep_nesting_stops(edited_crf):
    def edit(tree):
        mdv = tree.getroot().find(".//odm:MetaDataVersion", NS)
        form = [g for g in mdv.findall("odm:ItemGroupDef", NS) if g.get("OID") == "IG.FORM.AE/1"][0]
        form.find("odm:ItemGroupRef", NS).set("ItemGroupOID", "IG.DEEP.1")
        for n in range(1, MAX_DEPTH + 3):
            group = etree.SubElement(mdv, _odm.tag("ItemGroupDef"), OID=f"IG.DEEP.{n}", Name=f"Deep {n}",
                                     Repeating="No", Type="Section")
            etree.SubElement(group, _odm.tag("ItemGroupRef"), ItemGroupOID=f"IG.DEEP.{n + 1}", Mandatory="No")
            form.addnext(group)

    design = _design(edited_crf(edit))
    rows = design.walk("IG.FORM.AE/1")

    assert len(design.too_deep) == 1
    # the group past the cap gets its heading row and is not entered, so nothing lies deeper than it
    assert max(row.depth for row in rows) == MAX_DEPTH + 1
    assert rows[-1].kind == "group" and rows[-1].oid == f"IG.DEEP.{MAX_DEPTH + 1}"


def test_dangling_group_ref_gets_a_row(edited_crf):
    def edit(tree):
        mdv = tree.getroot().find(".//odm:MetaDataVersion", NS)
        form = [g for g in mdv.findall("odm:ItemGroupDef", NS) if g.get("OID") == "IG.FORM.AE/1"][0]
        form.find("odm:ItemGroupRef", NS).set("ItemGroupOID", "IG.NOPE")

    rows = _design(edited_crf(edit)).walk("IG.FORM.AE/1")
    assert [(row.kind, row.oid) for row in rows] == [("group", "IG.NOPE")]


# annotations

def test_group_annotations_by_level(synthetic):
    assert synthetic.group_annotations("IG.FORM.VS") == [("alias:formAnnotation", "DOMAIN = VS")]
    assert synthetic.group_annotations("IG.FORM.DM") == [("alias:SDTM", "DM")]
    assert synthetic.group_annotations("IG.FORM.CM") == [("attr:Domain", "CM")]
    assert synthetic.group_annotations("IG.SEC.VS") == [("alias:SDTM", "VS (Vital Signs)")]
    assert synthetic.group_annotations("IG.SEC.CM") == [("alias:formSectionAnnotation", "CM")]
    assert synthetic.group_annotations("IG.SEC.AE") == [("attr:Domain", "AE")]
    assert synthetic.group_annotations("IG.CON.SYSBP") == []
    assert synthetic.completion_instructions("IG.SEC.CM") == ["One row per medication."]


def test_group_and_context_domains(synthetic):
    assert synthetic.group_domain("IG.FORM.VS") == "VS"
    assert synthetic.group_domain("IG.SEC.VS") == "VS"
    assert synthetic.group_domain("IG.CON.SYSBP") is None
    assert synthetic.context_domain(("IG.FORM.VS", "IG.SEC.VS", "IG.CON.SYSBP")) == "VS"
    assert synthetic.known_domains == frozenset({"AE", "CM", "DM", "VS"})


def test_annotation_records(synthetic):
    records = synthetic.annotations()

    assert len(records) == 30
    levels = {record.level for record in records}
    assert levels == {"form", "section", "item", "codelist-item"}
    sex = [r for r in records if r.level == "codelist-item"]
    assert [(r.coded_value, r.text) for r in sex] == [("M", "DM.SEX=M"), ("F", "DM.SEX=F")]
    assert sex[0].item_oid == "IT.DM.SEX" and sex[0].codelist_oid == "CL.SEX"
    assert sex[0].group_path == ("IG.FORM.DM", "IG.SEC.DM")
    # a form's own annotation has the form as its path
    assert records[0].level == "form" and records[0].group_path == ("IG.FORM.DM",)


def test_parsed_annotations_resolve_datasets(synthetic):
    keys = {record.text: [t.key for t in parsed.targets] for record, parsed in synthetic.parsed_annotations()}

    assert keys["SEX"] == ["DM.SEX"]
    assert keys["VSDTC"] == ["VS.VSDTC"]
    assert keys["CMINDC in SUPPCM"] == ["SUPPCM.QVAL where QNAM = CMINDC"]
    assert keys["see protocol section 5"] == []


def test_result_common_section_domain_all_is_not_a_domain():
    design = _design(fixture_path("Result_ODMv2.xml"))
    assert "all" not in design.known_domains
    assert design.group_domain("IG_COMMON") is None
