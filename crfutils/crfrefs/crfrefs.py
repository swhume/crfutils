"""OID reference/definition integrity checking for CDISC ODM v2.0 CRFs.

A port of defineutils' definerefs. odmlib is the authority on *what* to check: create_oid_checker("odm_2_0")
introspects the model classes and supplies the ref/def mappings (single-target and any-of) and the skip
lists, so this module never hand-codes a reference table; a gap in the mapping is fixed in odmlib, not
supplemented here. The traversal is done here rather than via verify_oids(), so every problem is named
with its location. Two things are specific to ODM v2.0 CRFs: definitions and references are scoped to
their MetaDataVersion (OIDs are unique per MetaDataVersion, and files with several versions reuse them),
and a set of CRF-structure checks is run on the study design.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

from odmlib import create_oid_checker
from odmlib.odm_element import ODMElement

from .. import _common, _model
from .._design import CONCEPT, FORM, SECTION, StudyDesign
from . import report

SKIP_KEYS = _model.SKIP_KEYS
# elements whose references name a prior MetaDataVersion, often in another file: counted, not resolved
UNCHECKED_ELEMENTS = frozenset({"Include"})
# definitions that are legitimately referenced by nothing
ORPHAN_EXEMPT_ELEMENTS = frozenset({"Study", "MetaDataVersion"})

UNDEFINED_REFERENCE = "undefined_reference"
UNDEFINED_DOCUMENT_REFERENCE = "undefined_document_reference"
TYPE_MISMATCH = "type_mismatch"
DUPLICATE_OID = "duplicate_oid"
ITEMGROUP_CYCLE = "itemgroup_cycle"
ORPHAN_DEFINITION = "orphan_definition"
ORPHAN_DOCUMENT_LEAF = "orphan_document_leaf"
FORM_NESTED = "form_nested"
EVENT_REFERENCES_NON_FORM = "event_references_non_form"
CONCEPT_CONTAINS_GROUP = "concept_contains_group"
FORM_NOT_SCHEDULED = "form_not_scheduled"
EVENT_WITHOUT_FORMS = "event_without_forms"

ERROR = "error"
WARNING = "warning"


class CrfRefCheckError(Exception):
    pass


@dataclass(frozen=True)
class Location:
    element: str            # class name holding the reference/definition, e.g. "ItemRef"
    path: str               # "MetaDataVersion[MDV.1]/ItemGroupDef[IG.DM]"


@dataclass
class Finding:
    check: str              # "undefined_reference" | "type_mismatch" | "duplicate_oid" | ...
    severity: str           # "error" | "warning"
    oid: str
    attribute: Union[str, None]         # reference attribute, e.g. "ItemOID" (None for definitions)
    expected_element: Union[str, None]  # the class(es) the reference expects, "A or B" for any-of
    actual_element: Union[str, None]
    message: str            # self-contained sentence, used in the JSON report
    detail: str             # short form for the text listing, whose heading names oid/attribute
    locations: list = field(default_factory=list)


@dataclass
class RefCheckResult:
    crf_file: str
    model_package: str
    odmlib_version: str
    permissive: bool
    definition_count: int
    reference_count: int
    findings: list
    checked_attributes: list
    skipped_attributes: list
    unchecked_elements: list
    unmapped_attributes: list
    notes: list

    @property
    def errors(self) -> list:
        return [f for f in self.findings if f.severity == ERROR]

    @property
    def warnings(self) -> list:
        return [f for f in self.findings if f.severity == WARNING]

    @property
    def has_errors(self) -> bool:
        return any(f.severity == ERROR for f in self.findings)


class CrfRefChecker:
    def __init__(self, crf_file: Path, permissive: bool = False) -> None:
        self.crf_file = Path(crf_file)
        self.model_package = _model.MODEL_PACKAGE
        self.permissive = permissive
        self._result = None
        _common.require_file(self.crf_file, CrfRefCheckError)

    def check(self) -> RefCheckResult:
        """
        loads the CRF and runs every ref/def check; the result is cached so the report methods and the
        CLI exit code do not re-parse the file
        :return: RefCheckResult
        """
        if self._result is not None:
            return self._result
        checker = create_oid_checker(self.model_package)
        ref_def = dict(checker.ref_def)
        any_of = {attr: tuple(classes) for attr, classes in getattr(checker, "ref_def_any_of", {}).items()}
        id_defs = self._id_def_classes(ref_def, checker)
        # the load and the traversal share the permissive context: reading an unset required attribute
        # outside it raises, even though the __dict__ traversal avoids descriptors
        with _model.load_context(self.permissive):
            odm, root = _model.load_crf(self.crf_file, CrfRefCheckError, "No reference/definition checks were run",
                                        "re-run this check", "attempt a best-effort check of the file as-is",
                                        self.permissive)
            defs, refs, study_count = self._collect(odm, ref_def, any_of, id_defs)
            design = StudyDesign(_model.design_from_model(odm))
        single = study_count == 1
        findings = self._evaluate(defs, refs, checker, ref_def, any_of, id_defs, single)
        findings += self._structure_findings(design, single)
        findings.sort(key=lambda f: (f.severity != ERROR, f.check, f.oid, f.attribute or ""))
        present = {r["attr"] for r in refs if not r["unchecked"]}
        notes = []
        clinical = _model.clinical_data_note(root)
        if clinical:
            notes.append(clinical)
        self._result = RefCheckResult(
            crf_file=str(self.crf_file),
            model_package=self.model_package,
            odmlib_version=_model.odmlib_version(),
            permissive=self.permissive,
            definition_count=len(defs),
            reference_count=len(refs),
            findings=findings,
            checked_attributes=sorted((a for a in present if (a in ref_def or a in any_of)
                                       and a not in checker.skip_attr), key=str.lower),
            skipped_attributes=list(checker.skip_attr),
            unchecked_elements=sorted(UNCHECKED_ELEMENTS),
            unmapped_attributes=sorted((a for a in present if a not in ref_def and a not in any_of
                                        and a not in checker.skip_attr), key=str.lower),
            notes=notes,
        )
        return self._result

    def check_to_string(self, errors_only: bool = False, max_locations: int = 5) -> str:
        """
        runs the checks and returns the formatted text listing
        :param errors_only: when True, the warnings are suppressed
        :param max_locations: max example locations shown per finding (0 shows all)
        :return: string
        """
        return report.render_text(self.check(), errors_only, max_locations)

    def check_to_file(self, out_file: Path, errors_only: bool = False, max_locations: int = 5,
                      as_json: bool = False) -> None:
        """
        runs the checks and writes the listing (text or JSON) to out_file
        :param out_file: Path to the file to save the report
        :param errors_only: when True, the warnings are suppressed
        :param max_locations: max example locations shown per finding (0 shows all)
        :param as_json: when True, writes the JSON report instead of the text listing
        """
        if as_json:
            listing = self.check_to_json(errors_only=errors_only)
        else:
            listing = self.check_to_string(errors_only=errors_only, max_locations=max_locations)
        _common.write_text(out_file, listing + "\n", CrfRefCheckError)

    def check_to_console(self, errors_only: bool = False, max_locations: int = 5) -> None:
        """
        runs the checks and prints the formatted text listing to stdout
        :param errors_only: when True, the warnings are suppressed
        :param max_locations: max example locations shown per finding (0 shows all)
        """
        print(self.check_to_string(errors_only=errors_only, max_locations=max_locations))

    def check_to_json(self, errors_only: bool = False, indent: int = 2) -> str:
        """
        runs the checks and returns the results as a JSON string; every location is included even when
        the text listing truncates them
        :param errors_only: when True, the warnings are suppressed
        :param indent: JSON indent
        :return: string
        """
        return report.render_json(self.check(), errors_only, indent)

    @staticmethod
    def _id_def_classes(ref_def: dict, checker) -> set:
        """
        the definition classes that identify themselves with ID rather than OID (in ODM v2.0, Leaf).
        Derived from the model classes so it stays correct across odmlib releases
        """
        id_defs = set()
        for def_class in set(ref_def.values()):
            attrs = getattr(checker.model_classes.get(def_class), "_attrs", {})
            if "OID" not in attrs and "ID" in attrs:
                id_defs.add(def_class)
        return id_defs

    def _collect(self, root, ref_def: dict, any_of: dict, id_defs: set) -> tuple:
        """
        walks the loaded object tree once, collecting every OID definition and every reference
        occurrence with its element class name, path and MetaDataVersion scope
        :return: tuple of (definitions, references, the number of Study elements)
        """
        defs, refs = [], []
        self._walk(root, "", 1, None, defs, refs, ref_def, any_of, id_defs)
        study_count = len(_model.attr(root, "Study") or [])
        return defs, refs, study_count

    def _walk(self, elem, parent_path: str, ordinal: int, scope: Union[str, None], defs: list, refs: list,
              ref_def: dict, any_of: dict, id_defs: set) -> None:
        """
        recursive worker for _collect. Reads element.__dict__ rather than accessing attributes through
        the odmlib descriptors -- the technique odmlib's own _init_oid_check uses -- so an unset attribute
        on a permissively loaded file is simply absent. scope is the OID of the enclosing MetaDataVersion,
        None outside one (Study, AdminData)
        """
        cls = type(elem).__name__
        content = {k: v for k, v in elem.__dict__.items() if k not in SKIP_KEYS}
        own = content.get("OID") or (content.get("ID") if cls in id_defs else None)
        path = f"{parent_path}/{cls}[{own}]" if own else f"{parent_path}/{cls}"
        child_scope = own if cls == "MetaDataVersion" else scope
        counts = {}

        def visit(child):
            name = type(child).__name__
            counts[name] = counts.get(name, 0) + 1
            self._walk(child, path, counts[name], child_scope, defs, refs, ref_def, any_of, id_defs)

        for attr, obj in content.items():
            if isinstance(obj, ODMElement):
                visit(obj)
            elif isinstance(obj, list):
                for child in obj:
                    if isinstance(child, ODMElement):
                        visit(child)
            elif not isinstance(obj, str):
                continue
            elif attr == "OID" or (attr == "ID" and cls in id_defs):
                defs.append({"oid": obj, "elem": cls, "path": parent_path, "ordinal": ordinal, "scope": scope,
                             "type": content.get("Type") if cls == "ItemGroupDef" else None})
            elif "OID" in attr or attr in ref_def or attr in any_of:
                # an element that carries its own OID names itself in the location, so the reference is
                # recorded against the path that identifies it
                refs.append({"oid": obj, "attr": attr, "elem": cls, "path": path if own else parent_path,
                             "scope": scope, "unchecked": cls in UNCHECKED_ELEMENTS})

    def _evaluate(self, defs: list, refs: list, checker, ref_def: dict, any_of: dict, id_defs: set,
                  single: bool) -> list:
        """
        turns the collected definitions and references into findings: duplicate OIDs, dangling
        references, type mismatches and orphan definitions. Findings are grouped by (check, oid,
        attribute) with every occurrence appended as a Location
        """
        by_key, by_oid = {}, {}
        for definition in defs:
            by_key.setdefault((definition["scope"], definition["oid"]), []).append(definition)
            by_oid.setdefault(definition["oid"], []).append(definition)
        findings = self._duplicate_findings(by_key, single)
        findings += self._reference_findings(refs, by_key, by_oid, checker, ref_def, any_of, id_defs, single)
        findings += self._orphan_findings(refs, by_key, checker, ref_def, any_of, id_defs, single)
        return findings

    def _duplicate_findings(self, by_key: dict, single: bool) -> list:
        """uniqueness is checked for every definition within its MetaDataVersion (the XSD's unique
        constraints are per MetaDataVersion; files with several versions legitimately reuse OIDs),
        including the element types odmlib exempts from its orphan and target checks"""
        findings = []
        for (scope, oid), group in by_key.items():
            if len(group) < 2:
                continue
            detail, message = report.duplicate_text(oid, [(d["elem"], d["ordinal"]) for d in group], scope)
            findings.append(Finding(
                check=DUPLICATE_OID, severity=ERROR, oid=oid, attribute=None,
                expected_element=None, actual_element=group[0]["elem"],
                message=message, detail=detail,
                locations=[Location(d["elem"], _common.display_path(d["path"], single)) for d in group]))
        return findings

    def _reference_findings(self, refs: list, by_key: dict, by_oid: dict, checker, ref_def: dict, any_of: dict,
                            id_defs: set, single: bool) -> list:
        """dangling references and type mismatches. A reference resolves in its own MetaDataVersion
        first, then among the global definitions (Study, AdminData); resolution consults every definition,
        including the skipped element types, so a reference aimed at the wrong kind of element is reported
        as a precise type_mismatch rather than a vague not-found"""
        grouped = {}
        for ref in refs:
            attr, oid = ref["attr"], ref["oid"]
            if ref["unchecked"] or attr in checker.skip_attr or (attr not in ref_def and attr not in any_of):
                continue
            allowed = any_of.get(attr) or (ref_def[attr],)
            expected = report.expected_text(allowed)
            target = by_key.get((ref["scope"], oid)) or by_key.get((None, oid))
            if target is None:
                document = any(cls in id_defs for cls in allowed)
                elsewhere = sorted({d["scope"] for d in by_oid.get(oid, []) if d["scope"] is not None})
                check, actual = (UNDEFINED_DOCUMENT_REFERENCE if document else UNDEFINED_REFERENCE), None
                detail, message = report.undefined_text(attr, oid, allowed, document, elsewhere)
            elif target[0]["elem"] in allowed:
                continue
            else:
                check, actual = TYPE_MISMATCH, target[0]["elem"]
                detail, message = report.mismatch_text(attr, oid, allowed, actual)
            key = (check, oid, attr)
            if key not in grouped:
                grouped[key] = Finding(
                    check=check, severity=ERROR, oid=oid, attribute=attr,
                    expected_element=expected, actual_element=actual,
                    message=message, detail=detail, locations=[])
            grouped[key].locations.append(Location(ref["elem"], _common.display_path(ref["path"], single)))
        return list(grouped.values())

    def _orphan_findings(self, refs: list, by_key: dict, checker, ref_def: dict, any_of: dict, id_defs: set,
                         single: bool) -> list:
        """definitions nothing references. Any reference occurrence counts, including one made through an
        attribute odmlib skips or an unchecked element, so the warning cannot fire on an OID that is used.
        The ODM root, Study, MetaDataVersion and Form ItemGroupDefs are legitimately unreferenced"""
        referenced = {ref["oid"] for ref in refs}
        findings = []
        for (scope, oid), group in by_key.items():
            elem = group[0]["elem"]
            if oid in referenced or elem in checker.skip_elem or elem in ORPHAN_EXEMPT_ELEMENTS:
                continue
            if elem == "ItemGroupDef" and group[0]["type"] == FORM:
                continue
            # the attributes that could have referenced it: the single-target ones, or, for a class only the
            # workflow and timing references point at, the any-of ones
            via = sorted({a for a, target in ref_def.items() if target == elem and a not in checker.skip_attr}
                         or {a for a, targets in any_of.items() if elem in targets}, key=str.lower)
            detail, message = report.orphan_text(elem, oid, via)
            findings.append(Finding(
                check=ORPHAN_DOCUMENT_LEAF if elem in id_defs else ORPHAN_DEFINITION,
                severity=WARNING, oid=oid, attribute=None, expected_element=elem,
                actual_element=elem, message=message, detail=detail,
                locations=[Location(d["elem"], _common.display_path(d["path"], single)) for d in group]))
        return findings

    def _structure_findings(self, design: StudyDesign, single: bool) -> list:
        """the CRF-structure checks on the first MetaDataVersion's study design: ItemGroupRef cycles,
        nested forms, events collecting non-forms, concepts containing groups, and -- when the file has a
        visit schedule -- forms no visit collects and visits with no forms"""
        data = design.data
        if data.mdv_oid is None:
            return []
        prefix = f"/ODM/Study[{data.study_oid}]/MetaDataVersion[{data.mdv_oid}]"

        def where(element: str, container: str, oid: str) -> Location:
            return Location(element, _common.display_path(f"{prefix}/{container}[{oid}]", single))

        findings = []
        for form in design.forms:
            design.walk(form)
        for cycle in dict.fromkeys(design.cycles):
            detail, message = report.cycle_text(cycle)
            findings.append(Finding(ITEMGROUP_CYCLE, ERROR, cycle[-1], "ItemGroupOID", "ItemGroupDef", "ItemGroupDef",
                                    message, detail, [where("ItemGroupRef", "ItemGroupDef", cycle[-2])]))
        for group in data.groups.values():
            for child in group.children:
                if child.kind != "ItemGroupRef":
                    continue
                target = data.groups.get(child.oid)
                if target is None:
                    continue
                if target.type == FORM:
                    detail, message = report.structure_text(FORM_NESTED, child.oid, group.oid)
                    findings.append(Finding(FORM_NESTED, WARNING, child.oid, "ItemGroupOID", None, "ItemGroupDef",
                                            message, detail, [where("ItemGroupRef", "ItemGroupDef", group.oid)]))
                if group.type == CONCEPT and target.type in (SECTION, FORM):
                    detail, message = report.structure_text(CONCEPT_CONTAINS_GROUP, child.oid, group.oid, target.type)
                    findings.append(Finding(CONCEPT_CONTAINS_GROUP, WARNING, child.oid, "ItemGroupOID", None,
                                            "ItemGroupDef", message, detail,
                                            [where("ItemGroupRef", "ItemGroupDef", group.oid)]))
        for event in data.events.values():
            for ref in event.forms:
                target = data.groups.get(ref.oid)
                if target is not None and target.type != FORM:
                    detail, message = report.structure_text(EVENT_REFERENCES_NON_FORM, ref.oid, event.oid, target.type)
                    findings.append(Finding(EVENT_REFERENCES_NON_FORM, WARNING, ref.oid, "ItemGroupOID", None,
                                            "ItemGroupDef", message, detail,
                                            [where("ItemGroupRef", "StudyEventDef", event.oid)]))
        if design.has_schedule:
            for form in design.unscheduled_forms:
                detail, message = report.structure_text(FORM_NOT_SCHEDULED, form)
                findings.append(Finding(FORM_NOT_SCHEDULED, WARNING, form, None, None, "ItemGroupDef", message, detail,
                                        [where("ItemGroupDef", "ItemGroupDef", form)]))
            for event in design.events_without_forms:
                detail, message = report.structure_text(EVENT_WITHOUT_FORMS, event)
                findings.append(Finding(EVENT_WITHOUT_FORMS, WARNING, event, None, None, "StudyEventDef", message,
                                        detail, [where("StudyEventDef", "StudyEventDef", event)]))
        return findings
