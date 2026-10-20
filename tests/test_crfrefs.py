"""crfrefs: one mutation per check, the coverage of the odmlib mapping against the XSD, scoping, and goldens."""
import json
import os
from copy import deepcopy
from pathlib import Path

import pytest
import xmlschema
from lxml import etree

from conftest import DATA, FIXTURES, ROOT, SYNTHETIC, fixture_path
from crfutils import _odm
from crfutils.crfrefs import CrfRefChecker, CrfRefCheckError

NS = {"odm": _odm.ODM_NS}
GOLDEN = DATA / "golden"
XSD_NS = "http://www.w3.org/2001/XMLSchema"


def _mdv(tree):
    return tree.getroot().find(".//odm:MetaDataVersion", NS)


def _group(mdv, oid):
    return [g for g in mdv.findall("odm:ItemGroupDef", NS) if g.get("OID") == oid][0]


def _item_def(mdv, oid):
    return [d for d in mdv.findall("odm:ItemDef", NS) if d.get("OID") == oid][0]


def _item_ref(parent, item_oid):
    return [r for r in parent.findall("odm:ItemRef", NS) if r.get("ItemOID") == item_oid][0]


def _oids(result, check: str) -> list:
    return sorted(f.oid for f in result.findings if f.check == check)


def _checks(result) -> set:
    return {f.check for f in result.findings}


# the fixtures as they are

def test_synthetic_has_one_warning_and_no_errors():
    result = CrfRefChecker(SYNTHETIC).check()

    assert not result.has_errors
    assert [(f.check, f.oid, f.severity) for f in result.findings] == [("form_not_scheduled", "IG.FORM.AE/1", "warning")]
    assert result.findings[0].locations[0].path == "MetaDataVersion[MDV.1]/ItemGroupDef[IG.FORM.AE/1]"
    assert result.definition_count == 46 and result.reference_count == 50
    assert result.checked_attributes == ["CodeListOID", "CollectionExceptionConditionOID", "ItemGroupOID", "ItemOID",
                                         "LeafID", "MethodOID", "StudyEventGroupOID", "StudyEventOID", "UnitsItemOID"]
    assert result.skipped_attributes == ["FileOID", "PriorFileOID"]
    assert result.unchecked_elements == ["Include"]
    assert result.unmapped_attributes == []
    assert result.notes == []


@pytest.mark.parametrize("name, errors", [
    ("vital_signs_odmv2-0.xml", 0), ("cdash_demo_v20.xml", 0), ("Result_ODMv2.xml", 0), ("Atlas_QS_ODMv2.xml", 0),
    ("Demographics_RACE_check_all_that_apply.xml", 0), ("crf_synthetic.xml", 0),
    # the CDISC example has dangling ConditionOIDs in its workflow and a duplicate Transition OID
    ("Columbia-Suicide_Severity_Scale_ODMv2.xml", 12),
])
def test_fixture_error_counts(name, errors):
    result = CrfRefChecker(fixture_path(name)).check()
    assert len(result.errors) == errors
    assert result.unmapped_attributes == []


def test_columbia_errors_are_real_dangling_references():
    result = CrfRefChecker(fixture_path("Columbia-Suicide_Severity_Scale_ODMv2.xml")).check()

    assert _oids(result, "duplicate_oid") == ["TR.3-BRANCH-DESC"]
    undefined = [f for f in result.findings if f.check == "undefined_reference"]
    assert len(undefined) == 11
    assert {"ConditionOID", "CollectionExceptionConditionOID", "ItemOID", "SourceOID"} == {f.attribute for f in undefined}
    assert all(f.locations for f in undefined)
    assert result.notes == ["ClinicalData (1) not examined: crfutils checks ODM v2.0 metadata only"]


def test_result_cached():
    checker = CrfRefChecker(SYNTHETIC)
    assert checker.check() is checker.check()


# one mutation per check

def test_duplicate_oid(edited_crf):
    def edit(tree):
        item = _item_def(_mdv(tree), "IT.DM.AGE")
        item.addnext(deepcopy(item))

    result = CrfRefChecker(edited_crf(edit)).check()
    finding = [f for f in result.findings if f.check == "duplicate_oid"][0]
    assert finding.oid == "IT.DM.AGE" and finding.severity == "error"
    assert "defined by ItemDef (#" in finding.detail and "redefined by ItemDef (#" in finding.detail
    assert "in MetaDataVersion MDV.1" in finding.message
    assert len(finding.locations) == 2


def test_undefined_reference(edited_crf):
    def edit(tree):
        _item_ref(_group(_mdv(tree), "IG.SEC.AE"), "IT.AE.AESEV").set("ItemOID", "IT.NOPE")

    result = CrfRefChecker(edited_crf(edit)).check()
    finding = [f for f in result.findings if f.check == "undefined_reference"][0]
    assert (finding.oid, finding.attribute, finding.expected_element) == ("IT.NOPE", "ItemOID", "ItemDef")
    assert finding.detail == "expects an ItemDef; no element defines this OID"
    assert finding.locations[0].path == "MetaDataVersion[MDV.1]/ItemGroupDef[IG.SEC.AE]"
    assert finding.locations[0].element == "ItemRef"
    # the retargeted ItemRef leaves IT.AE.AESEV and its codelist's user intact, but AESEV itself is now an orphan
    assert _oids(result, "orphan_definition") == ["IT.AE.AESEV"]


def test_undefined_document_reference(edited_crf):
    def edit(tree):
        _mdv(tree).find("odm:AnnotatedCRF/odm:DocumentRef", NS).set("LeafID", "LF.NOPE")

    result = CrfRefChecker(edited_crf(edit)).check()
    assert _oids(result, "undefined_document_reference") == ["LF.NOPE"]
    finding = [f for f in result.findings if f.check == "undefined_document_reference"][0]
    assert "no Leaf defines this ID" in finding.detail
    assert _oids(result, "orphan_document_leaf") == ["LF.acrf"]


def test_type_mismatch(edited_crf):
    def edit(tree):
        _item_def(_mdv(tree), "IT.DM.SEX").find("odm:CodeListRef", NS).set("CodeListOID", "IT.DM.AGE")

    result = CrfRefChecker(edited_crf(edit)).check()
    finding = [f for f in result.findings if f.check == "type_mismatch"][0]
    assert (finding.oid, finding.attribute, finding.expected_element, finding.actual_element) == \
           ("IT.DM.AGE", "CodeListOID", "CodeList", "ItemDef")
    assert finding.detail == "expects a CodeList, but IT.DM.AGE is defined by an ItemDef"
    assert _oids(result, "orphan_definition") == ["CL.SEX"]


def test_orphan_definition(edited_crf):
    def edit(tree):
        mdv = _mdv(tree)
        orphan = deepcopy(_item_def(mdv, "IT.DM.AGE"))
        orphan.set("OID", "IT.ORPHAN")
        mdv.findall("odm:ItemDef", NS)[-1].addnext(orphan)

    result = CrfRefChecker(edited_crf(edit)).check()
    finding = [f for f in result.findings if f.check == "orphan_definition"][0]
    assert (finding.oid, finding.severity) == ("IT.ORPHAN", "warning")
    assert finding.detail == "ItemDef defined but never referenced (expected via ItemOID or UnitsItemOID)"
    assert not result.has_errors


def test_orphan_exemptions():
    # Study, MetaDataVersion and the unscheduled Form are legitimately unreferenced
    result = CrfRefChecker(SYNTHETIC).check()
    assert _oids(result, "orphan_definition") == []


def test_itemgroup_cycle(edited_crf):
    def edit(tree):
        concept = _group(_mdv(tree), "IG.CON.SYSBP")
        concept.append(etree.SubElement(concept, _odm.tag("ItemGroupRef"), ItemGroupOID="IG.SEC.VS", Mandatory="No"))

    result = CrfRefChecker(edited_crf(edit)).check()
    finding = [f for f in result.findings if f.check == "itemgroup_cycle"][0]
    assert (finding.oid, finding.severity) == ("IG.SEC.VS", "error")
    assert "IG.FORM.VS > IG.SEC.VS > IG.CON.SYSBP > IG.SEC.VS" in finding.detail
    assert finding.locations[0].path == "MetaDataVersion[MDV.1]/ItemGroupDef[IG.CON.SYSBP]"
    assert result.has_errors


def test_form_nested(edited_crf):
    def edit(tree):
        section = _group(_mdv(tree), "IG.SEC.DM")
        section.append(etree.SubElement(section, _odm.tag("ItemGroupRef"), ItemGroupOID="IG.FORM.AE/1", Mandatory="No"))

    result = CrfRefChecker(edited_crf(edit)).check()
    finding = [f for f in result.findings if f.check == "form_nested"][0]
    assert (finding.oid, finding.severity) == ("IG.FORM.AE/1", "warning")
    assert finding.locations[0].path == "MetaDataVersion[MDV.1]/ItemGroupDef[IG.SEC.DM]"


def test_event_references_non_form(edited_crf):
    def edit(tree):
        event = [e for e in _mdv(tree).findall("odm:StudyEventDef", NS) if e.get("OID") == "SE.COMMON"][0]
        event.find("odm:ItemGroupRef", NS).set("ItemGroupOID", "IG.SEC.CM")

    result = CrfRefChecker(edited_crf(edit)).check()
    finding = [f for f in result.findings if f.check == "event_references_non_form"][0]
    assert finding.oid == "IG.SEC.CM" and "a Section, not a Form" in finding.detail
    assert finding.locations[0].path == "MetaDataVersion[MDV.1]/StudyEventDef[SE.COMMON]"


def test_concept_contains_group(edited_crf):
    def edit(tree):
        concept = _group(_mdv(tree), "IG.CON.SYSBP")
        concept.append(etree.SubElement(concept, _odm.tag("ItemGroupRef"), ItemGroupOID="IG.SEC.AE", Mandatory="No"))

    result = CrfRefChecker(edited_crf(edit)).check()
    finding = [f for f in result.findings if f.check == "concept_contains_group"][0]
    assert finding.oid == "IG.SEC.AE" and finding.detail == "Concept references a Section"
    assert "itemgroup_cycle" not in _checks(result)


def test_form_not_scheduled_and_event_without_forms(edited_crf):
    def edit(tree):
        mdv = _mdv(tree)
        event = etree.Element(_odm.tag("StudyEventDef"), OID="SE.EMPTY", Name="Empty", Repeating="No", Type="Scheduled")
        mdv.find("odm:StudyEventDef", NS).addprevious(event)
        etree.SubElement(mdv.find("odm:StudyEventGroupDef", NS), _odm.tag("StudyEventRef"), StudyEventOID="SE.EMPTY",
                         Mandatory="No")

    result = CrfRefChecker(edited_crf(edit)).check()
    assert _oids(result, "form_not_scheduled") == ["IG.FORM.AE/1"]
    assert _oids(result, "event_without_forms") == ["SE.EMPTY"]
    assert not result.has_errors


def test_no_schedule_means_no_schedule_warnings():
    result = CrfRefChecker(fixture_path("vital_signs_odmv2-0.xml")).check()
    assert not {"form_not_scheduled", "event_without_forms"} & _checks(result)


# scoping by MetaDataVersion

def test_oids_are_scoped_to_their_metadataversion(edited_crf):
    def edit(tree):
        study = tree.getroot().find("odm:Study", NS)
        second = deepcopy(_mdv(tree))
        second.set("OID", "MDV.2")
        study.append(second)
        # a reference in MDV.2 to an OID that only MDV.1 defines
        _item_def(second, "IT.CM.CMTRT").set("OID", "IT.CM.CMTRT.V2")

    result = CrfRefChecker(edited_crf(edit)).check()
    # the reused OIDs are not duplicates
    assert "duplicate_oid" not in _checks(result)
    finding = [f for f in result.findings if f.check == "undefined_reference"][0]
    assert finding.oid == "IT.CM.CMTRT"
    assert "defined only in MetaDataVersion MDV.1" in finding.detail
    assert finding.locations[0].path == "MetaDataVersion[MDV.2]/ItemGroupDef[IG.SEC.CM]"
    assert _oids(result, "orphan_definition") == ["IT.CM.CMTRT.V2"]


def test_two_studies_keep_the_study_segment(edited_crf):
    def edit(tree):
        root = tree.getroot()
        second = deepcopy(root.find("odm:Study", NS))
        second.set("OID", "ST.OTHER")
        root.append(second)
        _item_ref(_group(second.find("odm:MetaDataVersion", NS), "IG.SEC.AE"), "IT.AE.AESEV").set("ItemOID", "IT.NOPE")

    result = CrfRefChecker(edited_crf(edit)).check()
    finding = [f for f in result.findings if f.check == "undefined_reference"][0]
    assert finding.locations[0].path == "Study[ST.OTHER]/MetaDataVersion[MDV.1]/ItemGroupDef[IG.SEC.AE]"


# coverage of the odmlib mapping

def _xsd_reference_attributes() -> dict:
    """(element, attribute) -> type for every oidref/IDREF attribute on an element reachable from Study in
    the bundled XSD, xhtml excluded"""
    xsd = xmlschema.XMLSchema(str(_odm.ODM_SCHEMA))
    seen, queue, found = set(), [xsd.elements["Study"]], {}
    while queue:
        element = queue.pop()
        if element.name in seen or element.target_namespace != _odm.ODM_NS:
            continue
        seen.add(element.name)
        for name, attribute in element.attributes.items():
            type_name = getattr(attribute.type, "local_name", None)
            if type_name in ("oidref", "IDREF"):
                found[(element.local_name, etree.QName(name).localname if "}" in name else name)] = type_name
        if element.type.has_complex_content():
            queue.extend(child for child in element.type.content.iter_elements() if getattr(child, "name", None))
    return found


def test_every_xsd_reference_attribute_is_checked_skipped_or_unchecked():
    from odmlib import create_oid_checker
    checker = create_oid_checker("odm_2_0")
    mapped = set(checker.ref_def) | set(checker.ref_def_any_of) | set(checker.skip_attr)
    unchecked_elements = {"Include"}

    references = _xsd_reference_attributes()
    assert len(references) > 30
    not_covered = {(element, attribute) for element, attribute in references
                   if attribute not in mapped and element not in unchecked_elements}
    assert not_covered == set(), "the odmlib mapping does not cover these XSD reference attributes"


def test_the_checked_mapping_is_pinned():
    from odmlib import create_oid_checker
    checker = create_oid_checker("odm_2_0")
    assert {"UnitsItemOID", "PartOfOrganizationOID", "ArchiveLocationID", "leafID", "LeafID", "TargetTransitionOID"} \
           <= set(checker.ref_def)
    assert set(checker.ref_def_any_of) == {"StartOID", "EndOID", "SourceOID", "TargetOID", "PredecessorOID",
                                           "SuccessorOID", "StructuralElementOID"}
    assert checker.skip_attr == ["FileOID", "PriorFileOID"]


# reports

def test_text_listing(edited_crf):
    def edit(tree):
        _item_ref(_group(_mdv(tree), "IG.SEC.AE"), "IT.AE.AESEV").set("ItemOID", "IT.NOPE")

    text = CrfRefChecker(edited_crf(edit)).check_to_string()

    assert text.startswith("ODM v2.0 OID reference/definition check\n  File:  ")
    assert "  Model: ODM v2.0 (odmlib odm_2_0, odmlib " in text
    assert "ERRORS (1)" in text and 'undefined_reference  ItemOID = "IT.NOPE"   (1 occurrence)' in text
    assert "WARNINGS (2)" in text
    assert "SUMMARY\n  1 error, 2 warnings in " in text
    assert "Checked attributes: CodeListOID" in text
    assert "Skipped attributes: FileOID, PriorFileOID" in text
    assert "Unchecked elements: Include" in text


def test_errors_only_and_max_locations(edited_crf):
    def edit(tree):
        for group in _mdv(tree).findall("odm:ItemGroupDef", NS):
            for ref in group.findall("odm:ItemRef", NS):
                ref.set("ItemOID", "IT.NOPE")

    checker = CrfRefChecker(edited_crf(edit))
    text = checker.check_to_string(errors_only=True, max_locations=2)
    assert "WARNINGS" not in text and "(warnings suppressed)" in text
    assert "... and 18 more" in text
    assert "... and" not in checker.check_to_string(max_locations=0)
    report = json.loads(checker.check_to_json(errors_only=True))
    assert report["errors_only"] is True and report["counts"]["warnings"] == 0
    assert len(report["findings"][0]["locations"]) == 20


def test_clean_listing_and_json():
    checker = CrfRefChecker(fixture_path("vital_signs_odmv2-0.xml"))
    assert "No OID reference/definition problems found." in checker.check_to_string()
    assert "No OID reference/definition errors found." in checker.check_to_string(errors_only=True)
    report = json.loads(checker.check_to_json())
    assert set(report) == {"crf_file", "model_package", "odmlib_version", "permissive", "errors_only", "counts",
                           "findings", "coverage", "notes"}
    assert report["counts"]["errors"] == 0 and report["findings"] == []
    assert set(report["coverage"]) == {"checked_attributes", "skipped_attributes", "unchecked_elements",
                                       "unmapped_attributes"}


def test_clinical_data_note_in_text_and_json():
    checker = CrfRefChecker(fixture_path("Atlas_QS_ODMv2.xml"))
    assert "NOTE: ClinicalData (1) not examined: crfutils checks ODM v2.0 metadata only" in checker.check_to_string()
    assert json.loads(checker.check_to_json())["notes"] == \
           ["ClinicalData (1) not examined: crfutils checks ODM v2.0 metadata only"]


def test_write_to_file(tmp_path):
    checker = CrfRefChecker(SYNTHETIC)
    checker.check_to_file(tmp_path / "r.txt")
    checker.check_to_file(tmp_path / "r.json", as_json=True)
    assert (tmp_path / "r.txt").read_text(encoding="utf-8") == checker.check_to_string() + "\n"
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["counts"]["warnings"] == 1
    with pytest.raises(CrfRefCheckError, match="write to a directory"):
        checker.check_to_file(tmp_path)


# goldens

def _golden_report(name: str, monkeypatch) -> dict:
    monkeypatch.chdir(ROOT)
    report = json.loads(CrfRefChecker(Path(os.path.relpath(fixture_path(name), ROOT))).check_to_json())
    report["odmlib_version"] = "(any)"
    return report


@pytest.mark.parametrize("name", ["Result_ODMv2.xml", "crf_synthetic.xml", "Columbia-Suicide_Severity_Scale_ODMv2.xml"])
def test_golden_json(name, monkeypatch):
    report = _golden_report(name, monkeypatch)
    golden = GOLDEN / f"crfrefs_{Path(name).stem}.json"
    if os.environ.get("CRFUTILS_UPDATE_GOLDEN"):
        golden.parent.mkdir(exist_ok=True)
        golden.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    assert golden.is_file(), f"run CRFUTILS_UPDATE_GOLDEN=1 pytest {__file__} to create {golden}"
    assert report == json.loads(golden.read_text(encoding="utf-8"))


# loading

def test_missing_file(tmp_path):
    with pytest.raises(CrfRefCheckError, match="not found"):
        CrfRefChecker(tmp_path / "nope.xml")


def test_v1_3_file_is_refused(tmp_path):
    crf = tmp_path / "odm13.xml"
    crf.write_text('<ODM xmlns="http://www.cdisc.org/ns/odm/v1.3" FileOID="F" FileType="Snapshot" '
                   'CreationDateTime="2026-01-01T00:00:00" ODMVersion="1.3.2"/>', encoding="utf-8")
    with pytest.raises(CrfRefCheckError, match="an ODM v1.3 document") as excinfo:
        CrfRefChecker(crf).check()
    assert "No reference/definition checks were run" in str(excinfo.value)


def test_non_conformant_file_suggests_permissive_and_loads_with_it(edited_crf):
    def edit(tree):
        del _item_def(_mdv(tree), "IT.DM.AGE").attrib["DataType"]

    crf = edited_crf(edit)
    with pytest.raises(CrfRefCheckError, match="add --permissive") as excinfo:
        CrfRefChecker(crf).check()
    assert f"crfvalidate -c {crf}" in str(excinfo.value)
    text = CrfRefChecker(crf, permissive=True).check_to_string()
    assert "NOTE: loaded in permissive mode" in text
    assert "run crfvalidate" in text


# the command

def test_cli_exit_codes(edited_crf, tmp_path, run_cli):
    def broken(tree):
        _item_ref(_group(_mdv(tree), "IG.SEC.AE"), "IT.AE.AESEV").set("ItemOID", "IT.NOPE")

    assert run_cli("crfrefs", "-c", str(SYNTHETIC)).returncode == 0
    completed = run_cli("crfrefs", "-c", str(edited_crf(broken)))
    assert completed.returncode == 1 and b"undefined_reference" in completed.stdout
    completed = run_cli("crfrefs", "-c", str(tmp_path / "nope.xml"))
    assert completed.returncode == 2 and b"not found" in completed.stderr
    completed = run_cli("crfrefs", "-c", str(SYNTHETIC), "-o", str(tmp_path))
    assert completed.returncode == 2 and b"write to a directory" in completed.stderr


def test_cli_json_and_options(tmp_path, run_cli):
    completed = run_cli("crfrefs", "-c", str(SYNTHETIC), "--json", "--errors-only", "-L", "1", "-o", str(tmp_path / "r.json"))
    assert completed.returncode == 0
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert report["errors_only"] is True and report["findings"] == []


def test_cli_permissive(edited_crf, run_cli):
    def edit(tree):
        del _item_def(_mdv(tree), "IT.DM.AGE").attrib["DataType"]

    crf = edited_crf(edit)
    assert run_cli("crfrefs", "-c", str(crf)).returncode == 2
    completed = run_cli("crfrefs", "-c", str(crf), "--permissive")
    assert completed.returncode == 0
    assert b"loaded in permissive mode" in completed.stdout
