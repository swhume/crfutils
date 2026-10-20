"""odmlib loading for crfrefs and crfmetrics, and the odmlib study-design extractor.

A port of definerefs' _load_define / _open_define / _permissive_would_load / _load_error_message. The
loader is odmlib's XMLODMLoader with the odm_2_0 model; the version gate runs on the ElementTree root the
loader parses, before the model load, so an ODM 1.3.2 file gets a clear refusal rather than an odmlib
type error. ClinicalData, ReferenceData and Association are out of scope (metadata only) and are noted,
never examined.
"""
from contextlib import nullcontext
from pathlib import Path
from typing import Union

import odmlib
import odmlib.loader as LD
import odmlib.odm_loader as OL
from odmlib import permissive as permissive_mode

from . import _design as D
from ._odm import ODM_NS, XLINK_NS, check_odm_v2

MODEL_PACKAGE = "odm_2_0"
MODEL_LABEL = "ODM v2.0"
# instance attributes odmlib might use for its own bookkeeping; not document content
SKIP_KEYS = {"_fields", "_attr_ns", "_elems", "_attrs", "_groups", "_group_of", "_markup"}
# the root children crfutils does not examine (D4a: metadata only)
DATA_ELEMENTS = ("ClinicalData", "ReferenceData", "Association")


def odmlib_version() -> str:
    return getattr(odmlib, "__version__", "unknown")


def model_label(model_package: str = MODEL_PACKAGE) -> str:
    return MODEL_LABEL if model_package == MODEL_PACKAGE else model_package


def open_crf(path: Path) -> tuple:
    """
    parses the file with odmlib's XML loader, without building the model yet
    :return: tuple of (the ODMLoader, the parsed ElementTree root)
    """
    loader = LD.ODMLoader(OL.XMLODMLoader(model_package=MODEL_PACKAGE, ns_uri=ODM_NS))
    root = loader.open_odm_document(str(path))
    return loader, root


def load_crf(path: Path, error_cls: type, nothing_done: str, rerun: str, best_effort: str,
             permissive: bool = False) -> tuple:
    """
    loads the CRF into the odmlib odm_2_0 model: parses it, applies the version gate to the parsed root,
    then builds the model objects. The caller wraps the call in odmlib.permissive() when it wants a
    best-effort load; permissive here only says whether the --permissive hint is still worth offering.
    Any failure becomes error_cls with the load-failure message, which recommends crfvalidate
    :param path: the ODM file
    :param error_cls: the exception class to raise
    :param nothing_done: e.g. "No reference/definition checks were run"
    :param rerun: e.g. "re-run this check"
    :param best_effort: e.g. "attempt a best-effort check of the file as-is"
    :param permissive: True when the caller is already loading permissively
    :return: tuple of (the root ODM object, the parsed ElementTree root)
    """
    try:
        loader, root = open_crf(path)
    except Exception as e:
        raise error_cls(load_error_message(path, e, nothing_done, rerun, best_effort, permissive)) from e
    check_odm_v2(root, path, error_cls, nothing_done)
    try:
        odm = loader.root()
    except Exception as e:
        raise error_cls(load_error_message(path, e, nothing_done, rerun, best_effort, permissive)) from e
    return odm, root


def permissive_would_load(path: Path) -> bool:
    """
    re-attempts a failed load inside the permissive context to find out whether suggesting --permissive
    is worth the user's time. Asking the file rather than testing the exception type keeps the guidance
    correct across odmlib releases
    :return: True when the file loads in permissive mode
    """
    try:
        with permissive_mode():
            loader, _ = open_crf(path)
            loader.root()
        return True
    except Exception:
        return False


def load_error_message(path: Path, e: Exception, nothing_done: str, rerun: str, best_effort: str,
                       permissive: bool) -> str:
    """
    builds the load failure message that recommends crfvalidate; the --permissive hint is added only
    when a permissive load of this file actually succeeds
    """
    message = (f"Unable to load {path} into the {MODEL_LABEL} model.\n"
               f"  {type(e).__name__}: {e}\n\n"
               f"{nothing_done}. This file must parse as conformant {MODEL_LABEL} before it can be\n"
               f"processed. Run crfvalidate to identify the problems:\n\n"
               f"    crfvalidate -c {path}\n\n"
               f"Then {rerun}.")
    if not permissive and permissive_would_load(path):
        message += f" To {best_effort},\nadd --permissive."
    return message


def load_context(permissive: bool):
    """the context a permissive load and traversal run in: reading an unset required attribute outside
    it raises, even though the __dict__ traversal avoids descriptors"""
    return permissive_mode() if permissive else nullcontext()


def clinical_data_note(root) -> Union[str, None]:
    """
    a note when the parsed document has ClinicalData, ReferenceData or Association, which crfutils
    does not examine
    :param root: the parsed ElementTree root
    :return: the note, or None
    """
    counts = []
    for name in DATA_ELEMENTS:
        count = sum(1 for child in root if isinstance(child.tag, str) and child.tag.endswith("}" + name))
        if count:
            counts.append(f"{name} ({count})")
    if not counts:
        return None
    return f"{', '.join(counts)} not examined: crfutils checks {MODEL_LABEL} metadata only"


# --- the odmlib study-design extractor -------------------------------------------------------------

def attr(elem, name: str):
    """
    reads one attribute or child out of the instance __dict__ rather than through the odmlib descriptor,
    so an unset attribute on a permissively loaded file returns None instead of raising, and an absent
    optional child needs no separate guard
    """
    return None if elem is None else elem.__dict__.get(name)


def text(elem) -> Union[str, None]:
    """the trimmed body text of a text element, which odmlib holds in _content; None when there is none"""
    content = attr(elem, "_content")
    if content is None:
        return None
    return content.strip() or None


def translated(parent, child_name: str) -> Union[str, None]:
    """the text of the first TranslatedText under parent/child_name"""
    child = attr(parent, child_name)
    texts = attr(child, "TranslatedText") or []
    return text(texts[0]) if texts else None


def _order(value) -> Union[int, None]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _aliases(elem) -> tuple:
    return tuple(D.Alias(attr(alias, "Context"), attr(alias, "Name")) for alias in attr(elem, "Alias") or [])


def _interleaved(elem, *names: str) -> list:
    """an element's children of the given names in document order, through odmlib's children(); falls
    back to the model order when the element has no children() (an older odmlib)"""
    if elem is None:
        return []
    if hasattr(elem, "children"):
        return elem.children(*names)
    return [child for name in names for child in attr(elem, name) or []]


def _child_ref(child) -> D.ChildRef:
    kind = type(child).__name__
    oid_attr = {"ItemRef": "ItemOID", "ItemGroupRef": "ItemGroupOID", "StudyEventRef": "StudyEventOID",
                "StudyEventGroupRef": "StudyEventGroupOID"}[kind]
    return D.ChildRef(kind, attr(child, oid_attr), _order(attr(child, "OrderNumber")), attr(child, "Mandatory"))


def design_from_model(odm) -> D.DesignData:
    """
    reads the study design from the first Study/MetaDataVersion of a loaded odmlib document; the same
    DesignData _odm.design_from_lxml reads from the XML. Call it inside load_context() on a permissive load
    :param odm: the root ODM object
    :return: DesignData
    """
    studies = attr(odm, "Study") or []
    study = studies[0] if studies else None
    mdvs = attr(study, "MetaDataVersion") or []
    mdv = mdvs[0] if mdvs else None
    data = D.DesignData(
        study_oid=attr(study, "OID"), study_name=attr(study, "StudyName"), protocol_name=attr(study, "ProtocolName"),
        mdv_oid=attr(mdv, "OID"), mdv_name=attr(mdv, "Name"), mdv_description=translated(mdv, "Description"))
    if mdv is None:
        return data
    for group in attr(mdv, "ItemGroupDef") or []:
        data.groups[attr(group, "OID")] = D.GroupDef(
            oid=attr(group, "OID"), name=attr(group, "Name"), type=attr(group, "Type"), domain=attr(group, "Domain"),
            aliases=_aliases(group),
            children=tuple(_child_ref(child) for child in _interleaved(group, "ItemRef", "ItemGroupRef")),
            description=translated(group, "Description"))
    for item in attr(mdv, "ItemDef") or []:
        data.items[attr(item, "OID")] = D.ItemDef(
            oid=attr(item, "OID"), name=attr(item, "Name"), datatype=attr(item, "DataType"),
            length=_order(attr(item, "Length")), aliases=_aliases(item),
            codelist_oid=attr(attr(item, "CodeListRef"), "CodeListOID"),
            question=translated(item, "Question"), prompt=translated(item, "Prompt"))
    for codelist in attr(mdv, "CodeList") or []:
        data.codelists[attr(codelist, "OID")] = D.CodeList(
            oid=attr(codelist, "OID"), name=attr(codelist, "Name"),
            items=tuple(D.CodeListItem(attr(cli, "CodedValue"), translated(cli, "Decode"), _aliases(cli))
                        for cli in attr(codelist, "CodeListItem") or []))
    for event in attr(mdv, "StudyEventDef") or []:
        data.events[attr(event, "OID")] = D.EventDef(
            oid=attr(event, "OID"), name=attr(event, "Name"), type=attr(event, "Type"),
            forms=tuple(_child_ref(ref) for ref in attr(event, "ItemGroupRef") or []))
    for group in attr(mdv, "StudyEventGroupDef") or []:
        data.event_groups[attr(group, "OID")] = D.EventGroupDef(
            oid=attr(group, "OID"), name=attr(group, "Name"),
            children=tuple(_child_ref(child)
                           for child in _interleaved(group, "StudyEventGroupRef", "StudyEventRef")))
    data.protocol = tuple(_child_ref(ref) for ref in attr(attr(mdv, "Protocol"), "StudyEventGroupRef") or [])
    leaves = {attr(leaf, "ID"): leaf for leaf in attr(mdv, "Leaf") or []}
    for ref in attr(attr(mdv, "AnnotatedCRF"), "DocumentRef") or []:
        leaf = leaves.get(attr(ref, "LeafID"))
        if leaf is not None:
            data.acrf_leaf = D.Leaf(attr(leaf, "ID"), attr(leaf, "href"), text(attr(leaf, "Title")))
            break
    return data
