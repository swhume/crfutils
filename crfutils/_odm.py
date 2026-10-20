"""ODM v2.0 constants, lxml parsing, the version gate, and the lxml study-design extractor.

Used by crfhtml, crfreview and crfpdf (lxml), and -- for the version gate only -- by crfrefs and
crfmetrics on the ElementTree root odmlib's loader returns.
"""
import re
from pathlib import Path
from typing import Union

from lxml import etree

from . import _design as D

ODM_NS = "http://www.cdisc.org/ns/odm/v2.0"
ODM_13_NS = "http://www.cdisc.org/ns/odm/v1.3"
XLINK_NS = "http://www.w3.org/1999/xlink"
XHTML_NS = "http://www.w3.org/1999/xhtml"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NSMAP = {"odm": ODM_NS, "xlink": XLINK_NS, "xhtml": XHTML_NS}

# the bundled ODM v2.0 schema; the entry point of the schema set crfvalidate validates against
ODM_SCHEMA = Path(__file__).parent.joinpath("validate", "schema", "odm-2-0", "ODM.xsd")

# ODM/@ODMVersion is optional; when present it must match the schema's ODMVersion pattern
ODM_VERSION_RE = re.compile(r"2\.0(\.(0|([1-9][0-9]*)))?(-([0-9a-zA-Z])+)*")

# the ItemGroupDef types a CRF is built from; any other Type renders and walks as a section
FORM, SECTION, CONCEPT = "Form", "Section", "Concept"


def tag(local: str) -> str:
    """the Clark-notation tag of an ODM v2.0 element"""
    return f"{{{ODM_NS}}}{local}"


def parse_odm(path: Path, error_cls: type) -> etree._ElementTree:
    """
    parses an ODM file with lxml. Comments are stripped so line numbers and child positions agree with
    crfvalidate, which parses the same way
    :param path: the ODM file
    :param error_cls: the exception class to raise
    :return: the parsed tree
    """
    try:
        return etree.parse(str(path), etree.XMLParser(remove_comments=True))
    except etree.XMLSyntaxError as e:
        raise error_cls(
            f"Unable to parse {path}: it is not well-formed XML.\n"
            f"  {e}\n\n"
            f"Run crfvalidate to identify the problems:\n\n"
            f"    crfvalidate -c {path}") from e
    except OSError as e:
        raise error_cls(f"Unable to read {path}.\n  {e}") from e


def not_v2_reason(root) -> Union[str, None]:
    """
    why a parsed root is not an ODM v2.0 document, or None when it is. Works on an lxml element or an
    ElementTree element: both expose .tag and .get()
    :param root: the document's root element
    :return: the reason, or None
    """
    root_tag = root.tag if isinstance(root.tag, str) else str(root.tag)
    if root_tag != tag("ODM"):
        if root_tag.startswith("{"):
            namespace, local = root_tag[1:].split("}", 1)
        else:
            namespace, local = "", root_tag
        if local == "ODM" and namespace == ODM_13_NS:
            return f"its root element is {root_tag}, an ODM v1.3 document"
        if local == "ODM" and namespace:
            return f"its root element is in the namespace {namespace}, not {ODM_NS}"
        if local == "ODM":
            return "its root element ODM has no namespace"
        return f"its root element is {root_tag}, not the ODM v2.0 ODM element"
    version = root.get("ODMVersion")
    if version is not None and not ODM_VERSION_RE.fullmatch(version):
        return f"ODMVersion '{version}' is not an ODM v2.0 version"
    return None


def check_odm_v2(root, path: Path, error_cls: type, consequence: str) -> None:
    """
    the version gate: the root must be the ODM v2.0 ODM element and, when ODMVersion is present, it must
    be an ODM v2.0 version. A file in another ODM version would otherwise render or load with most of its
    content silently missing, or fail with an odmlib type error
    :param root: the document's root element (lxml or ElementTree)
    :param path: the file, for the message
    :param error_cls: the exception class to raise
    :param consequence: what did not happen, e.g. "No HTML was generated"
    """
    reason = not_v2_reason(root)
    if reason is None:
        return
    raise error_cls(
        f"{path} is not an ODM v2.0 document: {reason}.\n\n"
        f"{consequence}. crfutils handles ODM v2.0 only. Run crfvalidate to check the file:\n\n"
        f"    crfvalidate -c {path}")


# --- the lxml study-design extractor ------------------------------------------------------------------

def _text(element) -> Union[str, None]:
    """an element's own text, trimmed; None when there is none"""
    if element is None or element.text is None:
        return None
    return element.text.strip() or None


def _order(value: Union[str, None]) -> Union[int, None]:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _aliases(element) -> tuple:
    return tuple(D.Alias(alias.get("Context"), alias.get("Name"))
                 for alias in element.findall(tag("Alias")))


def _translated(parent, child_name: str) -> Union[str, None]:
    """the text of the first TranslatedText under parent/child_name"""
    if parent is None:
        return None
    child = parent.find(tag(child_name))
    if child is None:
        return None
    return _text(child.find(tag("TranslatedText")))


def design_from_lxml(tree: etree._ElementTree) -> D.DesignData:
    """
    reads the study design -- forms, groups, items, codelists, events and the protocol schedule -- from
    the first Study/MetaDataVersion of a parsed ODM v2.0 document. _model.design_from_model reads the
    same design from odmlib objects, and a test asserts the two are equal on every fixture
    :param tree: the parsed document
    :return: DesignData
    """
    root = tree.getroot()
    study = root.find(tag("Study"))
    mdv = study.find(tag("MetaDataVersion")) if study is not None else None
    data = D.DesignData(
        study_oid=study.get("OID") if study is not None else None,
        study_name=study.get("StudyName") if study is not None else None,
        protocol_name=study.get("ProtocolName") if study is not None else None,
        mdv_oid=mdv.get("OID") if mdv is not None else None,
        mdv_name=mdv.get("Name") if mdv is not None else None,
        mdv_description=_translated(mdv, "Description"),
    )
    if mdv is None:
        return data
    for group in mdv.findall(tag("ItemGroupDef")):
        children = tuple(
            D.ChildRef(etree.QName(child).localname,
                       child.get("ItemOID") if etree.QName(child).localname == "ItemRef"
                       else child.get("ItemGroupOID"),
                       _order(child.get("OrderNumber")), child.get("Mandatory"))
            for child in group if isinstance(child.tag, str)
            and etree.QName(child).localname in ("ItemRef", "ItemGroupRef"))
        data.groups[group.get("OID")] = D.GroupDef(
            oid=group.get("OID"), name=group.get("Name"), type=group.get("Type"),
            domain=group.get("Domain"), aliases=_aliases(group), children=children,
            description=_translated(group, "Description"))
    for item in mdv.findall(tag("ItemDef")):
        codelist_ref = item.find(tag("CodeListRef"))
        data.items[item.get("OID")] = D.ItemDef(
            oid=item.get("OID"), name=item.get("Name"), datatype=item.get("DataType"),
            length=_order(item.get("Length")), aliases=_aliases(item),
            codelist_oid=codelist_ref.get("CodeListOID") if codelist_ref is not None else None,
            question=_translated(item, "Question"), prompt=_translated(item, "Prompt"))
    for codelist in mdv.findall(tag("CodeList")):
        data.codelists[codelist.get("OID")] = D.CodeList(
            oid=codelist.get("OID"), name=codelist.get("Name"),
            items=tuple(D.CodeListItem(cli.get("CodedValue"), _translated(cli, "Decode"), _aliases(cli))
                        for cli in codelist.findall(tag("CodeListItem"))))
    for event in mdv.findall(tag("StudyEventDef")):
        data.events[event.get("OID")] = D.EventDef(
            oid=event.get("OID"), name=event.get("Name"), type=event.get("Type"),
            forms=tuple(D.ChildRef("ItemGroupRef", ref.get("ItemGroupOID"), _order(ref.get("OrderNumber")),
                                   ref.get("Mandatory"))
                        for ref in event.findall(tag("ItemGroupRef"))))
    for group in mdv.findall(tag("StudyEventGroupDef")):
        data.event_groups[group.get("OID")] = D.EventGroupDef(
            oid=group.get("OID"), name=group.get("Name"),
            children=tuple(
                D.ChildRef(etree.QName(child).localname,
                           child.get("StudyEventOID") if etree.QName(child).localname == "StudyEventRef"
                           else child.get("StudyEventGroupOID"),
                           _order(child.get("OrderNumber")), child.get("Mandatory"))
                for child in group if isinstance(child.tag, str)
                and etree.QName(child).localname in ("StudyEventRef", "StudyEventGroupRef")))
    protocol = mdv.find(tag("Protocol"))
    if protocol is not None:
        data.protocol = tuple(D.ChildRef("StudyEventGroupRef", ref.get("StudyEventGroupOID"),
                                         _order(ref.get("OrderNumber")), ref.get("Mandatory"))
                              for ref in protocol.findall(tag("StudyEventGroupRef")))
    leaves = {leaf.get("ID"): leaf for leaf in mdv.findall(tag("Leaf"))}
    acrf = mdv.find(tag("AnnotatedCRF"))
    if acrf is not None:
        for ref in acrf.findall(tag("DocumentRef")):
            leaf = leaves.get(ref.get("LeafID"))
            if leaf is not None:
                data.acrf_leaf = D.Leaf(leaf.get("ID"), leaf.get(f"{{{XLINK_NS}}}href"),
                                        _text(leaf.find(tag("Title"))))
                break
    return data
