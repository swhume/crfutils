"""crfvalidate: schema validation against the bundled ODM v2.0 schema, with grouped findings."""
import json
from pathlib import Path

import pytest
import xmlschema
from lxml import etree

from conftest import DATA, FIXTURES, SYNTHETIC, fixture_path
from crfutils.validate import CrfSchemaLoadError, CrfSchemaValidationError, CrfSchemaValidator, DEFAULT_SCHEMA

ODM_NS = "http://www.cdisc.org/ns/odm/v2.0"
NS = {"odm": ODM_NS}

BAD_DATATYPE = "NOT_A_DATATYPE"


def _mdv(tree):
    return tree.getroot().find(".//odm:MetaDataVersion", NS)


def _item_def(mdv, oid):
    return [d for d in mdv.findall("odm:ItemDef", NS) if d.get("OID") == oid][0]


def _write_simple_schema(tmp_path: Path) -> tuple:
    """a standalone schema and a document that matches it, so the schema override can be tested without
    depending on the semantics of the CDISC schema"""
    xsd_file = tmp_path / "simple.xsd"
    xsd_file.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
    <xs:element name="Greeting" type="xs:string"/>
</xs:schema>""", encoding="utf-8")
    xml_file = tmp_path / "simple.xml"
    xml_file.write_text("<Greeting>hello</Greeting>", encoding="utf-8")
    return xsd_file, xml_file


@pytest.fixture
def broken_crf(edited_crf) -> Path:
    """the synthetic CRF broken in four ways that stay well-formed: the same invalid DataType on two
    ItemDefs (which must group into one finding), a removed required attribute, and an unexpected child"""
    def edit(tree):
        mdv = _mdv(tree)
        _item_def(mdv, "IT.VS.SYSBP").set("DataType", BAD_DATATYPE)
        _item_def(mdv, "IT.DM.AGE").set("DataType", BAD_DATATYPE)
        del _item_def(mdv, "IT.AE.AETERM").attrib["DataType"]
        group = mdv.findall("odm:ItemGroupDef", NS)[0]
        group.append(etree.SubElement(group, f"{{{ODM_NS}}}Bogus"))

    return edited_crf(edit)


def _raw_error_count(crf: Path, schema: Path) -> int:
    """the ground truth: what xmlschema itself finds, independent of the code under test"""
    xsd = xmlschema.XMLSchema(str(schema))
    return len(list(xsd.iter_errors(etree.parse(str(crf), etree.XMLParser(remove_comments=True)))))


def _checks(result) -> set:
    return {f.check for f in result.findings}


# the bundled schema and the fixtures

def test_the_default_schema_is_the_bundled_odm_v2_schema():
    assert DEFAULT_SCHEMA == Path(__file__).parent.parent / "crfutils" / "validate" / "schema" / "odm-2-0" / "ODM.xsd"
    assert DEFAULT_SCHEMA.is_file()
    assert CrfSchemaValidator(SYNTHETIC).xsd_file == DEFAULT_SCHEMA


@pytest.mark.parametrize("name", FIXTURES)
def test_every_fixture_is_valid(name):
    result = CrfSchemaValidator(fixture_path(name)).validate()

    assert result.is_valid
    assert result.error_count == 0
    assert result.root_namespace == ODM_NS
    assert result.namespace_note is None


def test_result_is_cached():
    validator = CrfSchemaValidator(SYNTHETIC)
    assert validator.validate() is validator.validate()


# findings

def test_broken_crf_groups_identical_errors(broken_crf):
    result = CrfSchemaValidator(broken_crf).validate()

    assert not result.is_valid
    assert result.has_errors
    assert result.error_count == _raw_error_count(broken_crf, DEFAULT_SCHEMA)
    assert result.error_count > len(result.findings)
    # the two bad DataTypes are one finding with two locations, each with a line and an OID path
    bad = [f for f in result.findings if BAD_DATATYPE in f.reason]
    assert len(bad) == 1
    assert bad[0].element == "ItemDef"
    assert {loc.path for loc in bad[0].locations} == {"MetaDataVersion[MDV.1]/ItemDef[IT.VS.SYSBP]",
                                                      "MetaDataVersion[MDV.1]/ItemDef[IT.DM.AGE]"}
    assert all(isinstance(loc.line, int) and loc.line > 0 for loc in bad[0].locations)
    assert {"invalid_value", "attribute_error", "unexpected_child"} <= _checks(result)
    # the biggest problem is listed first
    assert [len(f.locations) for f in result.findings] == sorted((len(f.locations) for f in result.findings),
                                                                reverse=True)


def test_text_listing(broken_crf):
    text = CrfSchemaValidator(broken_crf).validate_to_string()

    assert text.startswith("ODM v2.0 schema validation\n  File:   ")
    assert f"  Schema: {DEFAULT_SCHEMA}" in text
    assert "ERRORS (" in text
    assert "(2 occurrences)" in text
    assert "- line " in text
    assert "SUMMARY" in text


def test_max_locations_truncates_the_listing_but_not_the_json(broken_crf):
    validator = CrfSchemaValidator(broken_crf)

    text = validator.validate_to_string(max_locations=1)
    report = json.loads(validator.validate_to_json())

    assert "... and 1 more" in text
    bad = [f for f in report["findings"] if BAD_DATATYPE in f["reason"]][0]
    assert len(bad["locations"]) == 2
    assert "... and" not in validator.validate_to_string(max_locations=0)


def test_json_shape(broken_crf):
    report = json.loads(CrfSchemaValidator(broken_crf).validate_to_json())

    assert set(report) == {"crf_file", "schema_file", "xmlschema_version", "root_namespace", "valid", "counts",
                           "findings", "notes"}
    assert report["valid"] is False
    assert report["root_namespace"] == ODM_NS
    assert report["counts"] == {"errors": _raw_error_count(broken_crf, DEFAULT_SCHEMA), "findings": len(report["findings"])}
    assert set(report["findings"][0]) == {"check", "severity", "element", "reason", "message", "detail", "locations"}
    assert report["notes"] == []


def test_valid_file_listing_and_json():
    validator = CrfSchemaValidator(SYNTHETIC)

    assert "No schema validation errors found." in validator.validate_to_string()
    report = json.loads(validator.validate_to_json())
    assert report["valid"] is True and report["findings"] == []


# the version and namespace note

def test_odm_v1_3_file_gets_a_namespace_note(tmp_path):
    crf = tmp_path / "odm13.xml"
    crf.write_text('<ODM xmlns="http://www.cdisc.org/ns/odm/v1.3" FileOID="F" FileType="Snapshot" '
                   'CreationDateTime="2026-01-01T00:00:00" ODMVersion="1.3.2"/>', encoding="utf-8")
    validator = CrfSchemaValidator(crf)

    result = validator.validate()
    assert not result.is_valid
    assert result.root_namespace == "http://www.cdisc.org/ns/odm/v1.3"
    assert "bundled schema is ODM v2.0" in result.namespace_note
    assert "NOTE: the root element is in the namespace http://www.cdisc.org/ns/odm/v1.3" in validator.validate_to_string()
    assert json.loads(validator.validate_to_json())["notes"] == [result.namespace_note]


def test_another_schema_gets_no_namespace_note(tmp_path):
    xsd_file, xml_file = _write_simple_schema(tmp_path)
    validator = CrfSchemaValidator(xml_file, xsd_file)

    result = validator.validate()
    assert result.is_valid
    assert result.schema_file == str(xsd_file)
    assert result.namespace_note is None


# failures

def test_missing_file_is_a_load_error(tmp_path):
    with pytest.raises(CrfSchemaLoadError, match="not found"):
        CrfSchemaValidator(tmp_path / "nope.xml").validate()


def test_malformed_file_is_a_load_error(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("<ODM><broken></ODM>", encoding="utf-8")
    with pytest.raises(CrfSchemaLoadError, match="not well-formed"):
        CrfSchemaValidator(bad).validate()


def test_missing_schema_is_a_load_error(tmp_path):
    with pytest.raises(CrfSchemaLoadError, match="Could not load the schema"):
        CrfSchemaValidator(SYNTHETIC, tmp_path / "nope.xsd")


def test_load_error_is_a_validation_error():
    assert issubclass(CrfSchemaLoadError, CrfSchemaValidationError)


def test_write_to_folder_is_reported(tmp_path):
    with pytest.raises(CrfSchemaLoadError, match="write to a directory"):
        CrfSchemaValidator(SYNTHETIC).validate_to_file(tmp_path)


def test_write_to_file_and_json(tmp_path):
    validator = CrfSchemaValidator(SYNTHETIC)
    validator.validate_to_file(tmp_path / "report.txt")
    validator.validate_to_file(tmp_path / "report.json", as_json=True)

    assert (tmp_path / "report.txt").read_text(encoding="utf-8") == validator.validate_to_string() + "\n"
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["valid"] is True


# the command

def test_cli_valid_file_exits_0(run_cli):
    completed = run_cli("crfvalidate", "-c", str(SYNTHETIC))

    assert completed.returncode == 0
    assert b"No schema validation errors found." in completed.stdout
    assert completed.stderr == b""


def test_cli_invalid_file_exits_1(broken_crf, run_cli):
    completed = run_cli("crfvalidate", "-c", str(broken_crf), "-L", "0")

    assert completed.returncode == 1
    assert b"ERRORS (" in completed.stdout


def test_cli_missing_file_exits_2(tmp_path, run_cli):
    completed = run_cli("crfvalidate", "-c", str(tmp_path / "nope.xml"))

    assert completed.returncode == 2
    assert completed.stdout == b""
    assert b"not found" in completed.stderr


def test_cli_json_and_out(broken_crf, tmp_path, run_cli):
    completed = run_cli("crfvalidate", "-c", str(broken_crf), "--json", "-o", str(tmp_path / "r.json"))

    assert completed.returncode == 1
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["valid"] is False


def test_cli_schema_override(tmp_path, run_cli):
    xsd_file, xml_file = _write_simple_schema(tmp_path)

    completed = run_cli("crfvalidate", "-c", str(xml_file), "-s", str(xsd_file))

    assert completed.returncode == 0
    assert str(xsd_file).encode() in completed.stdout


def test_cli_write_to_folder_exits_2(tmp_path, run_cli):
    completed = run_cli("crfvalidate", "-c", str(SYNTHETIC), "-o", str(tmp_path))

    assert completed.returncode == 2
    assert b"write to a directory" in completed.stderr


def test_schema_folder_has_no_init():
    assert not (DATA.parent.parent / "crfutils" / "validate" / "schema" / "odm-2-0" / "__init__.py").exists()
