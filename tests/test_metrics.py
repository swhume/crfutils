"""crfmetrics: the model-derived element inventory, the element counts, and the CRF, annotation and visit metrics."""
import inspect
import json
from collections import Counter
from pathlib import Path

import pytest
import xmlschema
from lxml import etree
from odmlib.odm_element import ODMElement

from conftest import FIXTURES, SYNTHETIC, fixture_path
from crfutils import _odm
from crfutils.metrics import CrfMetrics, CrfMetricsError

NS = {"odm": _odm.ODM_NS}


def _raw_counts(path: Path) -> Counter:
    """An independent census: every element counted by local name, with no odmlib involved, skipping the
    root children crfutils does not examine (ClinicalData and friends) and comments"""
    counts = Counter()
    root = etree.parse(str(path)).getroot()
    counts["ODM"] += 1
    for child in root:
        if not isinstance(child.tag, str) or etree.QName(child).localname in ("ClinicalData", "ReferenceData", "Association"):
            continue
        for element in child.iter():
            if isinstance(element.tag, str) and etree.QName(element).namespace == _odm.ODM_NS:
                counts[etree.QName(element).localname] += 1
    return counts


def _model_element_classes() -> set:
    """The element classes the odmlib odm_2_0 model itself declares"""
    import odmlib.odm_2_0.model as model
    return {name for name, obj in vars(model).items()
            if inspect.isclass(obj) and issubclass(obj, ODMElement) and obj.__module__ == model.__name__}


def _xsd_elements_from_study() -> set:
    """every ODM element reachable from Study in the bundled XSD, xhtml excluded"""
    xsd = xmlschema.XMLSchema(str(_odm.ODM_SCHEMA))
    seen, queue = set(), [xsd.elements["Study"]]
    while queue:
        element = queue.pop()
        if element.name in seen or element.target_namespace != _odm.ODM_NS:
            continue
        seen.add(element.name)
        if element.type.has_complex_content():
            queue.extend(child for child in element.type.content.iter_elements() if getattr(child, "name", None))
    return {name.split("}")[-1] for name in seen}


@pytest.fixture(scope="module")
def synthetic():
    return CrfMetrics(SYNTHETIC).collect()


@pytest.fixture(scope="module")
def result_file():
    return CrfMetrics(fixture_path("Result_ODMv2.xml")).collect()


# the inventory

def test_inventory_is_the_model_closure_from_odm(synthetic):
    inventory = [e.element for e in synthetic.elements]
    assert len(inventory) == 124
    assert len(set(inventory)) == 124
    assert inventory[0] == "ODM"
    # every element the inventory names is a model class, and every XSD element reachable from Study is in it
    assert set(inventory) <= _model_element_classes() | {"ODM"}
    missing = _xsd_elements_from_study() - set(inventory)
    assert missing == set(), f"XSD elements the inventory does not count: {missing}"


def test_inventory_sections(synthetic):
    sections = {e.element: e.section for e in synthetic.elements}
    assert sections["ODM"] == "document" and sections["Study"] == "document" and sections["MetaDataVersion"] == "document"
    assert sections["AdminData"] == "document"
    assert sections["ItemGroupDef"] == "definitions" and sections["Leaf"] == "definitions"
    assert sections["ItemRef"] == "nested" and sections["TranslatedText"] == "document"
    assert sections["User"] == "admin" and sections["Organization"] == "admin" and sections["Address"] == "admin"
    assert Counter(e.section for e in synthetic.elements)["admin"] == 24


# the counts

@pytest.mark.parametrize("name", FIXTURES)
def test_counts_match_an_independent_census(name):
    result = CrfMetrics(fixture_path(name)).collect()
    counted = {e.element: e.count for e in result.elements}
    raw = _raw_counts(fixture_path(name))
    for element, count in raw.items():
        assert counted.get(element) == count, element
    assert result.total_elements == sum(raw.values())


def test_absent_elements_are_reported_as_zero(synthetic):
    assert synthetic.count("WorkflowDef") == 0
    assert synthetic.count("ValueListDef") == 0
    assert synthetic.count("Nope") == 0
    assert synthetic.element_types_absent > 0
    assert synthetic.element_types_present + synthetic.element_types_absent == synthetic.element_types


# the CRF metrics

def test_synthetic_crf_metrics(synthetic):
    crf = synthetic.crf
    assert (crf.forms, crf.scheduled_forms, crf.unscheduled_forms) == (4, 3, 1)
    assert (crf.sections, crf.concepts, crf.other_groups) == (5, 1, 0)
    assert (crf.item_defs, crf.item_rows, crf.distinct_items, crf.mandatory_rows) == (22, 22, 22, 8)
    assert crf.items_by_datatype == {"text": 14, "date": 5, "integer": 2, "float": 1}
    assert (crf.codelists, crf.codelist_items) == (7, 17)
    assert (crf.condition_defs, crf.method_defs, crf.workflow_defs) == (1, 1, 0)


def test_synthetic_visit_metrics(synthetic):
    visits = synthetic.visits
    assert (visits.study_events, visits.study_event_groups, visits.links, visits.matrix_cells) == (3, 1, 5, 12)
    assert visits.fill == pytest.approx(5 / 12)
    assert visits.unscheduled_forms == ["IG.FORM.AE/1"] and visits.events_without_forms == []


def test_synthetic_annotation_metrics(synthetic):
    a = synthetic.annotations
    assert (a.annotated_items, a.distinct_items, a.annotated_pct) == (22, 22, 100.0)
    assert (a.form_annotations, a.section_annotations, a.concept_annotations, a.item_annotations,
            a.codelist_item_annotations) == (3, 5, 0, 22, 2)
    assert (a.parsed, a.partial, a.unparsed, a.not_submitted) == (31, 0, 1, 3)
    assert a.datasets == ["AE", "CM", "DM", "SUPPCM", "VS"]
    assert a.unresolved_datasets == 0
    assert a.unparsed_texts == ["see protocol section 5"]
    assert a.unannotated_items == []


def test_synthetic_form_table(synthetic):
    rows = {f.oid: f for f in synthetic.forms}
    assert list(rows) == ["IG.FORM.DM", "IG.FORM.VS", "IG.FORM.CM", "IG.FORM.AE/1"]
    vs = rows["IG.FORM.VS"]
    assert (vs.name, vs.domains, vs.sections, vs.concepts, vs.items, vs.annotated, vs.not_submitted, vs.visits) == \
           ("Vital Signs", ["VS"], 1, 1, 6, 6, 1, 2)
    assert rows["IG.FORM.AE/1"].visits == 0 and rows["IG.FORM.CM"].not_submitted == 2


def test_result_counts(result_file):
    assert result_file.crf.forms == 7
    assert result_file.visits.study_events == 5
    assert result_file.visits.links == 11
    assert result_file.crf.item_rows == 90 and result_file.crf.item_defs == 63
    assert result_file.annotations.datasets == ["AE", "CM", "DM", "LB", "QS", "SU", "VS"]
    assert result_file.mdv_count == 1


def test_vital_signs_has_no_schedule():
    result = CrfMetrics(fixture_path("vital_signs_odmv2-0.xml")).collect()
    assert (result.crf.forms, result.crf.scheduled_forms, result.crf.unscheduled_forms) == (1, 0, 1)
    assert result.visits.links == 0 and result.visits.fill is None
    assert result.visits.unscheduled_forms == []
    assert result.annotations.annotated_pct == 100.0


def test_atlas_has_unresolved_datasets_and_a_note():
    result = CrfMetrics(fixture_path("Atlas_QS_ODMv2.xml")).collect()
    assert result.annotations.unresolved_datasets > 0
    assert result.annotations.datasets == []
    assert result.notes == ["ClinicalData (1) not examined: crfutils checks ODM v2.0 metadata only"]


def test_identity(synthetic):
    assert (synthetic.study_oid, synthetic.study_name, synthetic.protocol_name) == ("ST.SYNTH", "SYNTH", "SYNTH-001")
    assert (synthetic.file_oid, synthetic.file_type, synthetic.granularity, synthetic.odm_version) == \
           ("FILE.SYNTH.1", "Snapshot", "Metadata", "2.0")
    assert (synthetic.mdv_oid, synthetic.mdv_name) == ("MDV.1", "Synthetic CRF metadata")
    assert synthetic.study_description == "Synthetic study for the crfutils tests"
    assert synthetic.size_bytes == SYNTHETIC.stat().st_size
    assert synthetic.standards == []


# reports

def test_text_report(synthetic):
    text = CrfMetrics(SYNTHETIC).collect_to_string()
    for heading in ("ODM v2.0 CRF metrics", "STUDY", "CRF", "ANNOTATIONS", "FORMS (4)", "ELEMENT COUNTS",
                    "  Administrative data", "SUMMARY"):
        assert heading in text
    assert "  Forms:             4 (3 scheduled, 1 unscheduled)" in text
    assert "  Items annotated:   22 of 22 (100%)" in text
    assert "  Visit-form links:  5 (matrix 3 x 4, 42% filled)" in text
    assert "4 forms, 22 item rows, 22 item definitions, 7 code lists, 1 method, 5 visit-form links" in text
    assert "FORMS" not in CrfMetrics(SYNTHETIC).collect_to_string(show_forms=False)


def test_json_shape(synthetic):
    report = json.loads(CrfMetrics(SYNTHETIC).collect_to_json())
    assert set(report) == {"crf_file", "model_package", "odmlib_version", "permissive", "file", "document", "study",
                           "standards", "element_counts", "crf", "annotations", "visits", "forms", "totals", "notes"}
    assert report["study"]["metadata_version"]["count"] == 1
    assert len(report["element_counts"]) == 124 and set(report["element_counts"][0]) == {"element", "section", "count"}
    assert len(report["forms"]) == 4
    assert report["annotations"]["unannotated_items"] == []
    assert report["totals"]["element_types"] == 124


def test_write_to_file(tmp_path):
    metrics = CrfMetrics(SYNTHETIC)
    metrics.collect_to_file(tmp_path / "m.txt")
    metrics.collect_to_file(tmp_path / "m.json", as_json=True)
    assert (tmp_path / "m.txt").read_text(encoding="utf-8") == metrics.collect_to_string() + "\n"
    assert json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))["crf"]["forms"] == 4
    with pytest.raises(CrfMetricsError, match="write to a directory"):
        metrics.collect_to_file(tmp_path)


def test_multiple_mdvs_are_noted(edited_crf):
    from copy import deepcopy

    def edit(tree):
        study = tree.getroot().find("odm:Study", NS)
        second = deepcopy(study.find("odm:MetaDataVersion", NS))
        second.set("OID", "MDV.2")
        study.append(second)

    result = CrfMetrics(edited_crf(edit)).collect()
    assert result.mdv_count == 2
    assert result.crf.forms == 4
    assert "the Study has 2 MetaDataVersions; the CRF metrics describe the first" in result.notes
    assert "(1 of 2 versions)" in CrfMetrics(edited_crf(edit)).collect_to_string()


# loading

def test_missing_file(tmp_path):
    with pytest.raises(CrfMetricsError, match="not found"):
        CrfMetrics(tmp_path / "nope.xml")


def test_non_conformant_file_suggests_permissive(edited_crf):
    def edit(tree):
        del tree.getroot().find(".//odm:ItemDef", NS).attrib["DataType"]

    crf = edited_crf(edit)
    with pytest.raises(CrfMetricsError, match="No metrics were collected") as excinfo:
        CrfMetrics(crf).collect()
    assert "add --permissive" in str(excinfo.value)
    result = CrfMetrics(crf, permissive=True).collect()
    assert result.permissive and result.crf.item_defs == 22
    assert result.crf.items_by_datatype["(none)"] == 1
    assert "NOTE: loaded in permissive mode" in CrfMetrics(crf, permissive=True).collect_to_string()


# the command

def test_cli(tmp_path, run_cli):
    completed = run_cli("crfmetrics", "-c", str(SYNTHETIC))
    assert completed.returncode == 0 and b"ODM v2.0 CRF metrics" in completed.stdout
    completed = run_cli("crfmetrics", "-c", str(SYNTHETIC), "--json", "--no-forms", "-o", str(tmp_path / "m.json"))
    assert completed.returncode == 0
    assert len(json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))["forms"]) == 4
    completed = run_cli("crfmetrics", "-c", str(tmp_path / "nope.xml"))
    assert completed.returncode == 2 and b"not found" in completed.stderr
    completed = run_cli("crfmetrics", "-c", str(fixture_path("Atlas_QS_ODMv2.xml")))
    assert b"NOTE: ClinicalData (1) not examined" in completed.stdout.split(b"STUDY")[0]
