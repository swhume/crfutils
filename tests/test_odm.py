"""_odm: lxml parsing and the ODM v2.0 version gate, on lxml and ElementTree roots."""
import xml.etree.ElementTree as ET

import pytest
from lxml import etree

from conftest import SYNTHETIC
from crfutils import _odm

V13 = "http://www.cdisc.org/ns/odm/v1.3"


class Refused(Exception):
    pass


def _roots(xml: str) -> list:
    """the same document parsed by lxml and by ElementTree, since the gate must work on both"""
    return [etree.fromstring(xml.encode("utf-8")), ET.fromstring(xml)]


@pytest.mark.parametrize("xml", [
    f'<ODM xmlns="{_odm.ODM_NS}" ODMVersion="2.0"/>',
    f'<ODM xmlns="{_odm.ODM_NS}" ODMVersion="2.0.1"/>',
    f'<ODM xmlns="{_odm.ODM_NS}" ODMVersion="2.0.0-draft1"/>',
    f'<ODM xmlns="{_odm.ODM_NS}"/>',
], ids=["2.0", "2.0.1", "2.0.0-draft1", "no ODMVersion"])
def test_odm_v2_roots_pass(xml):
    for root in _roots(xml):
        assert _odm.not_v2_reason(root) is None
        _odm.check_odm_v2(root, "crf.xml", Refused, "Nothing was done")


@pytest.mark.parametrize("xml, reason", [
    (f'<ODM xmlns="{V13}" ODMVersion="1.3.2"/>', "an ODM v1.3 document"),
    (f'<ODM xmlns="{_odm.ODM_NS}" ODMVersion="1.3.2"/>', "ODMVersion '1.3.2' is not an ODM v2.0 version"),
    (f'<ODM xmlns="{_odm.ODM_NS}" ODMVersion="2.01"/>', "ODMVersion '2.01' is not an ODM v2.0 version"),
    (f'<ODM xmlns="{_odm.ODM_NS}" ODMVersion="2.0 "/>', "is not an ODM v2.0 version"),
    ('<ODM/>', "has no namespace"),
    ('<ODM xmlns="urn:other"/>', "in the namespace urn:other"),
    (f'<Study xmlns="{_odm.ODM_NS}"/>', "not the ODM v2.0 ODM element"),
], ids=["v1.3 namespace", "v1.3 version", "2.01", "trailing space", "no namespace", "other namespace", "not ODM"])
def test_other_roots_are_refused(xml, reason):
    for root in _roots(xml):
        assert reason in _odm.not_v2_reason(root)
        with pytest.raises(Refused) as excinfo:
            _odm.check_odm_v2(root, "crf.xml", Refused, "Nothing was done")
        message = str(excinfo.value)
        assert message.startswith("crf.xml is not an ODM v2.0 document: ")
        assert reason in message
        assert "Nothing was done. crfutils handles ODM v2.0 only." in message
        assert "crfvalidate -c crf.xml" in message


def test_parse_odm_strips_comments():
    tree = _odm.parse_odm(SYNTHETIC, Refused)

    assert not [node for node in tree.getroot().iter() if not isinstance(node.tag, str)]
    assert tree.getroot().tag == _odm.tag("ODM")


def test_parse_odm_malformed_names_crfvalidate(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("<ODM><broken></ODM>", encoding="utf-8")

    with pytest.raises(Refused, match="not well-formed XML") as excinfo:
        _odm.parse_odm(bad, Refused)
    assert f"crfvalidate -c {bad}" in str(excinfo.value)


def test_parse_odm_missing_file(tmp_path):
    with pytest.raises(Refused, match="Unable to read"):
        _odm.parse_odm(tmp_path / "nope.xml", Refused)


def test_the_bundled_schema_exists():
    assert _odm.ODM_SCHEMA.is_file()
    assert _odm.ODM_SCHEMA.name == "ODM.xsd"
