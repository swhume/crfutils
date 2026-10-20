"""_model: the odmlib load, the version gate before it, the load-failure message, and the data note."""
import xml.etree.ElementTree as ET

import pytest
from lxml import etree

from conftest import FIXTURES, SYNTHETIC, fixture_path
from crfutils import _model, _odm

NS = {"odm": _odm.ODM_NS}


class Refused(Exception):
    pass


def _load(path, permissive=False):
    return _model.load_crf(path, Refused, "Nothing was done", "re-run this", "try harder", permissive)


@pytest.mark.parametrize("name", FIXTURES)
def test_every_fixture_loads_strictly(name):
    # this guards the odmlib ODM v2.0 fixes crfrefs and crfmetrics depend on (CRF_UTILS_PLAN.md section 4A)
    odm, root = _load(fixture_path(name))

    assert type(odm).__name__ == "ODM"
    assert isinstance(root, ET.Element)
    assert root.tag == _odm.tag("ODM")


def test_odmlib_has_the_odm_v2_fixes():
    odm, _ = _load(fixture_path("Demographics_RACE_check_all_that_apply.xml"))
    group = [g for g in odm.Study[0].MetaDataVersion[0].ItemGroupDef if g.OID == "IG.DEMOGRAPHICS"][0]
    # interleaved ItemRef/ItemGroupRef children keep their document order (fix O5)
    assert [type(c).__name__ for c in group.children("ItemRef", "ItemGroupRef")] == \
           ["ItemRef", "ItemRef", "ItemRef", "ItemGroupRef"]
    from odmlib import create_oid_checker
    checker = create_oid_checker("odm_2_0")
    # the four references 0.2.1 never checked (fix O6)
    assert checker.ref_def["UnitsItemOID"] == "ItemDef"
    assert checker.ref_def["PartOfOrganizationOID"] == "Organization"
    assert checker.ref_def["ArchiveLocationID"] == "Leaf"
    assert checker.ref_def["leafID"] == "Leaf"


def test_v1_3_file_is_refused_before_the_model_load(tmp_path):
    crf = tmp_path / "odm13.xml"
    crf.write_text('<ODM xmlns="http://www.cdisc.org/ns/odm/v1.3" FileOID="F" FileType="Snapshot" '
                   'CreationDateTime="2026-01-01T00:00:00" ODMVersion="1.3.2"><Study OID="S"/></ODM>', encoding="utf-8")

    with pytest.raises(Refused, match="an ODM v1.3 document") as excinfo:
        _load(crf)
    message = str(excinfo.value)
    assert "Nothing was done. crfutils handles ODM v2.0 only." in message
    assert "Unable to load" not in message


def test_malformed_file_message_names_crfvalidate(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("<ODM><broken></ODM>", encoding="utf-8")

    with pytest.raises(Refused) as excinfo:
        _load(bad)
    message = str(excinfo.value)
    assert message.startswith(f"Unable to load {bad} into the ODM v2.0 model.")
    assert "Nothing was done. This file must parse as conformant ODM v2.0" in message
    assert f"crfvalidate -c {bad}" in message
    assert "Then re-run this." in message
    assert "--permissive" not in message


def test_permissive_hint_only_when_a_permissive_load_would_succeed(edited_crf):
    def drop_required_attribute(tree):
        item = tree.getroot().find(".//odm:ItemDef", NS)
        del item.attrib["DataType"]

    crf = edited_crf(drop_required_attribute)
    assert _model.permissive_would_load(crf)
    with pytest.raises(Refused) as excinfo:
        _load(crf)
    assert "To try harder,\nadd --permissive." in str(excinfo.value)
    # once loading permissively, the hint is pointless
    with pytest.raises(Refused) as excinfo:
        _load(crf, permissive=True)
    assert "--permissive" not in str(excinfo.value)
    # and inside the permissive context the file loads
    with _model.load_context(True):
        odm, _ = _load(crf, permissive=True)
    assert odm is not None


def test_clinical_data_note():
    _, atlas = _load(fixture_path("Atlas_QS_ODMv2.xml"))
    assert _model.clinical_data_note(atlas) == "ClinicalData (1) not examined: crfutils checks ODM v2.0 metadata only"
    _, synthetic = _load(SYNTHETIC)
    assert _model.clinical_data_note(synthetic) is None


def test_clinical_data_note_counts_every_data_element():
    root = ET.fromstring(f'<ODM xmlns="{_odm.ODM_NS}"><ClinicalData/><ClinicalData/><ReferenceData/><Association/>'
                         f'<Study/></ODM>')
    assert _model.clinical_data_note(root) == ("ClinicalData (2), ReferenceData (1), Association (1) not examined: "
                                               "crfutils checks ODM v2.0 metadata only")


def test_design_from_model_identity_and_leaf():
    odm, _ = _load(SYNTHETIC)
    data = _model.design_from_model(odm)

    assert (data.study_oid, data.study_name, data.mdv_oid) == ("ST.SYNTH", "SYNTH", "MDV.1")
    assert data.acrf_leaf.href == "acrf.pdf"
    assert list(data.groups)[:2] == ["IG.FORM.AE/1", "IG.FORM.VS"]
    assert [c.oid for c in data.groups["IG.SEC.VS"].children] == ["IT.VS.VSPERF", "IG.CON.SYSBP", "IT.VS.VSDTC"]


def test_design_from_model_without_a_study():
    class Empty:
        __dict__ = {}

    data = _model.design_from_model(Empty())
    assert data.study_oid is None and data.groups == {}


def test_helpers_read_the_instance_dict():
    odm, _ = _load(SYNTHETIC)
    mdv = odm.Study[0].MetaDataVersion[0]
    assert _model.attr(mdv, "OID") == "MDV.1"
    assert _model.attr(mdv, "Include") is None
    assert _model.attr(None, "OID") is None
    assert _model.translated(mdv, "Description") == "Blank annotated CRFs covering the annotation vocabularies"
    assert _model.translated(mdv, "Nope") is None
    assert _model.text(None) is None
