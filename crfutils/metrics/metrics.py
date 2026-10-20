"""Metrics reporting for CDISC ODM v2.0 CRFs.

A port of defineutils' definemetrics. The list of elements to count is derived from the odmlib odm_2_0
model rather than hand-maintained: the closure of child elements reachable from the model root supplies
every element type the document *can* hold, so one that is absent from a file is reported as 0 instead
of missing from the report. The CRF, annotation and visit metrics come from the study design
(_design.StudyDesign) read from the same loaded objects.
"""
import importlib
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Union

from odmlib.odm_element import ODMElement

from .. import _common, _model
from .. import annotations as A
from .._design import CONCEPT, FORM, SECTION, StudyDesign
from . import report

SKIP_KEYS = _model.SKIP_KEYS
# the element the section rule pivots on: its children are the document's definitions
DEFINITION_PARENT = "MetaDataVersion"
# everything under this element is administrative data
ADMIN_PARENT = "AdminData"
# the model root class; every model package in the ODM family names it ODM
ROOT_ELEMENT = "ODM"

DOCUMENT = "document"
DEFINITIONS = "definitions"
NESTED = "nested"
ADMIN = "admin"


class CrfMetricsError(Exception):
    pass


@dataclass(frozen=True)
class ElementCount:
    element: str            # model class name, e.g. "ItemDef"
    section: str            # "document" | "definitions" | "nested" | "admin"
    count: int


@dataclass(frozen=True)
class StandardInfo:
    oid: str
    name: Union[str, None]
    type: Union[str, None]
    publishing_set: Union[str, None]
    version: Union[str, None]
    status: Union[str, None]


@dataclass(frozen=True)
class CrfCounts:
    forms: int
    scheduled_forms: int
    unscheduled_forms: int
    sections: int
    concepts: int
    other_groups: int
    item_defs: int
    item_rows: int              # item occurrences on forms (an ItemDef on two forms counts twice)
    distinct_items: int         # distinct ItemDefs on forms
    mandatory_rows: int
    items_by_datatype: dict     # DataType -> ItemDef count
    codelists: int
    codelist_items: int
    condition_defs: int
    method_defs: int
    workflow_defs: int


@dataclass(frozen=True)
class VisitMetrics:
    study_events: int
    study_event_groups: int
    links: int                  # visit-form links (StudyEventDef/ItemGroupRef to a Form)
    matrix_cells: int           # visits x forms
    fill: Union[float, None]    # links / matrix_cells
    unscheduled_forms: list
    events_without_forms: list


@dataclass(frozen=True)
class AnnotationMetrics:
    annotated_items: int        # distinct items on forms with an SDTM annotation
    distinct_items: int
    annotated_pct: Union[float, None]
    form_annotations: int
    section_annotations: int
    concept_annotations: int
    item_annotations: int
    codelist_item_annotations: int
    not_submitted: int
    parsed: int
    partial: int
    unparsed: int
    unresolved_datasets: int    # targets whose dataset could not be resolved
    datasets: list              # the datasets referenced, sorted
    unparsed_texts: list        # JSON only
    unannotated_items: list     # JSON only


@dataclass(frozen=True)
class FormMetrics:
    oid: str
    name: Union[str, None]
    domains: list
    sections: int
    concepts: int
    items: int
    annotated: int
    not_submitted: int
    visits: int


@dataclass
class MetricsResult:
    crf_file: str
    model_package: str
    odmlib_version: str
    permissive: bool
    size_bytes: int
    file_modified: str                          # ISO 8601, from st_mtime
    creation_datetime: Union[str, None]         # ODM/@CreationDateTime, verbatim
    file_oid: Union[str, None]
    file_type: Union[str, None]
    granularity: Union[str, None]
    originator: Union[str, None]
    source_system: Union[str, None]
    source_system_version: Union[str, None]
    odm_version: Union[str, None]
    study_oid: Union[str, None]
    study_name: Union[str, None]
    protocol_name: Union[str, None]
    study_description: Union[str, None]
    mdv_oid: Union[str, None]
    mdv_name: Union[str, None]
    mdv_description: Union[str, None]
    mdv_count: int
    crf: CrfCounts
    annotations: AnnotationMetrics
    visits: VisitMetrics
    standards: list = field(default_factory=list)    # StandardInfo
    elements: list = field(default_factory=list)     # ElementCount, in model order
    forms: list = field(default_factory=list)        # FormMetrics, in display order
    notes: list = field(default_factory=list)

    @property
    def total_elements(self) -> int:
        return sum(e.count for e in self.elements)

    @property
    def element_types(self) -> int:
        return len(self.elements)

    @property
    def element_types_present(self) -> int:
        return sum(1 for e in self.elements if e.count)

    @property
    def element_types_absent(self) -> int:
        return sum(1 for e in self.elements if not e.count)

    def count(self, element: str) -> int:
        """the count for one element type by model class name, 0 when the model has no such element"""
        return next((e.count for e in self.elements if e.element == element), 0)


class CrfMetrics:
    def __init__(self, crf_file: Path, permissive: bool = False) -> None:
        self.crf_file = Path(crf_file)
        self.model_package = _model.MODEL_PACKAGE
        self.permissive = permissive
        self._result = None
        _common.require_file(self.crf_file, CrfMetricsError)

    def collect(self) -> MetricsResult:
        """
        loads the CRF and collects every metric; the result is cached so the report methods and the CLI
        do not re-parse the file
        :return: MetricsResult
        """
        if self._result is not None:
            return self._result
        model = self._model_module()
        inventory = self._element_inventory(model)
        # the load, the traversal and every attribute read share the permissive context: reading an unset
        # required attribute outside it raises
        with _model.load_context(self.permissive):
            odm, root = _model.load_crf(self.crf_file, CrfMetricsError, "No metrics were collected",
                                        "re-run these metrics", "collect best-effort metrics from the file as-is",
                                        self.permissive)
            counts = self._count_elements(odm)
            design = StudyDesign(_model.design_from_model(odm))
            self._result = self._build_result(odm, root, inventory, counts, design)
        return self._result

    def collect_to_string(self, show_forms: bool = True) -> str:
        """
        collects the metrics and returns the formatted text report
        :param show_forms: when False, the per-form table is omitted
        :return: string
        """
        return report.render_text(self.collect(), show_forms)

    def collect_to_file(self, out_file: Path, show_forms: bool = True, as_json: bool = False) -> None:
        """
        collects the metrics and writes the report (text or JSON) to out_file
        :param out_file: Path to the file to save the report
        :param show_forms: when False, the per-form table is omitted from the text report
        :param as_json: when True, writes the JSON report instead of the text report
        """
        if as_json:
            listing = self.collect_to_json()
        else:
            listing = self.collect_to_string(show_forms=show_forms)
        _common.write_text(out_file, listing + "\n", CrfMetricsError)

    def collect_to_console(self, show_forms: bool = True) -> None:
        """
        collects the metrics and prints the formatted text report to stdout
        :param show_forms: when False, the per-form table is omitted
        """
        print(self.collect_to_string(show_forms=show_forms))

    def collect_to_json(self, indent: int = 2) -> str:
        """
        collects the metrics and returns them as a JSON string; the forms are always included, even when
        the text report suppresses them
        :param indent: JSON indent
        :return: string
        """
        return report.render_json(self.collect(), indent)

    def _model_module(self):
        """imports the odmlib model module the metrics are derived from and loaded into"""
        try:
            return importlib.import_module(f"odmlib.{self.model_package}.model")
        except ImportError as e:
            raise CrfMetricsError(f"Unable to import the odmlib model package {self.model_package}.\n{e}") from e

    def _element_inventory(self, model) -> list:
        """
        walks the model breadth-first from the root element and returns every element type the model can
        hold, in discovery order, each with the report section it belongs to. Breadth-first matters: an
        element reachable at two depths takes the shallower reading
        :param model: the odmlib model module
        :return: list of (class, section) tuples
        """
        root = getattr(model, ROOT_ELEMENT, None)
        if root is None:
            raise CrfMetricsError(f"The odmlib model package {self.model_package} has no {ROOT_ELEMENT} root element.")
        inventory, seen = [], {ROOT_ELEMENT}
        queue = deque([(root, None, False, False)])
        while queue:
            cls, parent, under_definitions, under_admin = queue.popleft()
            inventory.append((cls, self._section(cls.__name__, parent, under_definitions, under_admin)))
            defines = cls.__name__ == DEFINITION_PARENT
            admin = cls.__name__ == ADMIN_PARENT
            for name, descriptor in cls._elems.items():
                if name in seen:
                    continue
                seen.add(name)
                # resolve by name against the model module, the way odmlib's loader does
                child = getattr(model, name, descriptor.element_class)
                queue.append((child, cls.__name__, under_definitions or defines, under_admin or admin))
        return inventory

    @staticmethod
    def _section(element: str, parent: Union[str, None], under_definitions: bool, under_admin: bool) -> str:
        """
        the report section an element type belongs to, derived from where the walk first reached it
        rather than from a curated list
        """
        if under_admin:
            return ADMIN
        if element == DEFINITION_PARENT or not under_definitions:
            return DOCUMENT
        return DEFINITIONS if parent == DEFINITION_PARENT else NESTED

    def _count_elements(self, root) -> Counter:
        """counts every element in the loaded document by model class name in a single pass"""
        counts = Counter()
        self._count(root, counts)
        return counts

    def _count(self, elem, counts: Counter) -> None:
        """
        recursive worker for _count_elements. Reads element.__dict__ rather than accessing attributes
        through the odmlib descriptors, so an unset attribute on a permissively loaded file is simply
        absent
        """
        counts[type(elem).__name__] += 1
        for attr, obj in elem.__dict__.items():
            if attr in SKIP_KEYS:
                continue
            if isinstance(obj, ODMElement):
                self._count(obj, counts)
            elif isinstance(obj, list):
                for child in obj:
                    if isinstance(child, ODMElement):
                        self._count(child, counts)

    def _build_result(self, odm, root, inventory: list, counts: Counter, design: StudyDesign) -> MetricsResult:
        """assembles the MetricsResult; called inside the permissive context so unset attributes cannot raise"""
        attr, text = _model.attr, _model.text
        studies = attr(odm, "Study") or []
        study = studies[0] if studies else None
        mdvs = attr(study, "MetaDataVersion") or []
        mdv = mdvs[0] if mdvs else None
        stat = self.crf_file.stat()
        notes = []
        clinical = _model.clinical_data_note(root)
        if clinical:
            notes.append(clinical)
        if len(studies) > 1:
            notes.append(f"the file has {len(studies)} Study elements; the CRF metrics describe the first")
        if len(mdvs) > 1:
            notes.append(f"the Study has {len(mdvs)} MetaDataVersions; the CRF metrics describe the first")
        annotations = self._annotation_metrics(design)
        return MetricsResult(
            crf_file=str(self.crf_file),
            model_package=self.model_package,
            odmlib_version=_model.odmlib_version(),
            permissive=self.permissive,
            size_bytes=stat.st_size,
            # st_birthtime is not available on every platform, so this is the modified time
            file_modified=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            creation_datetime=attr(odm, "CreationDateTime"),
            file_oid=attr(odm, "FileOID"),
            file_type=attr(odm, "FileType"),
            granularity=attr(odm, "Granularity"),
            originator=attr(odm, "Originator"),
            source_system=attr(odm, "SourceSystem"),
            source_system_version=attr(odm, "SourceSystemVersion"),
            odm_version=attr(odm, "ODMVersion"),
            study_oid=attr(study, "OID"),
            study_name=attr(study, "StudyName"),
            protocol_name=attr(study, "ProtocolName"),
            study_description=_model.translated(study, "Description"),
            mdv_oid=attr(mdv, "OID"),
            mdv_name=attr(mdv, "Name"),
            mdv_description=_model.translated(mdv, "Description"),
            mdv_count=len(mdvs),
            crf=self._crf_metrics(mdv, design),
            annotations=annotations,
            visits=self._visit_metrics(mdv, design),
            standards=self._standards(mdv),
            elements=[ElementCount(element=cls.__name__, section=section, count=counts.get(cls.__name__, 0))
                      for cls, section in inventory],
            forms=self._form_metrics(design),
            notes=notes,
        )

    def _standards(self, mdv) -> list:
        """the Standard elements the MetaDataVersion references, in document order"""
        attr = _model.attr
        container = attr(mdv, "Standards")
        return [StandardInfo(oid=attr(std, "OID"), name=attr(std, "Name"), type=attr(std, "Type"),
                             publishing_set=attr(std, "PublishingSet"), version=attr(std, "Version"),
                             status=attr(std, "Status"))
                for std in attr(container, "Standard") or []]

    @staticmethod
    def _crf_metrics(mdv, design: StudyDesign) -> CrfCounts:
        attr = _model.attr
        data = design.data
        groups = list(data.groups.values())
        rows = [row for form in design.forms for row in design.items_on(form)]
        distinct = {row.oid for row in rows}
        datatypes = Counter(item.datatype or "(none)" for item in data.items.values())
        return CrfCounts(
            forms=len(design.forms),
            scheduled_forms=len(design.forms) - len(design.unscheduled_forms) if design.has_schedule else 0,
            unscheduled_forms=len(design.unscheduled_forms) if design.has_schedule else len(design.forms),
            sections=sum(1 for g in groups if g.type == SECTION),
            concepts=sum(1 for g in groups if g.type == CONCEPT),
            other_groups=sum(1 for g in groups if g.type not in (FORM, SECTION, CONCEPT)),
            item_defs=len(data.items),
            item_rows=len(rows),
            distinct_items=len(distinct),
            mandatory_rows=sum(1 for row in rows if row.mandatory == "Yes"),
            items_by_datatype=dict(sorted(datatypes.items(), key=lambda kv: (-kv[1], kv[0]))),
            codelists=len(data.codelists),
            codelist_items=sum(len(c.items) for c in data.codelists.values()),
            condition_defs=len(attr(mdv, "ConditionDef") or []),
            method_defs=len(attr(mdv, "MethodDef") or []),
            workflow_defs=len(attr(mdv, "WorkflowDef") or []),
        )

    @staticmethod
    def _visit_metrics(mdv, design: StudyDesign) -> VisitMetrics:
        attr = _model.attr
        links = sum(len(refs) for refs in design.schedule.values())
        cells = len(design.visits) * len(design.forms)
        return VisitMetrics(
            study_events=len(design.data.events),
            study_event_groups=len(attr(mdv, "StudyEventGroupDef") or []),
            links=links,
            matrix_cells=cells,
            fill=(links / cells) if cells else None,
            unscheduled_forms=list(design.unscheduled_forms) if design.has_schedule else [],
            events_without_forms=list(design.events_without_forms) if design.has_schedule else [],
        )

    @staticmethod
    def _annotation_metrics(design: StudyDesign) -> AnnotationMetrics:
        rows = [row for form in design.forms for row in design.items_on(form)]
        distinct = {row.oid for row in rows}
        by_level = Counter()
        annotated, not_submitted, datasets, unparsed_texts = set(), 0, set(), []
        status = Counter()
        unresolved = 0
        for record, parsed in design.parsed_annotations():
            by_level[record.level] += 1
            if record.level in ("item", "codelist-item"):
                annotated.add(record.item_oid)
            if parsed.not_submitted:
                not_submitted += 1
            status[parsed.status] += 1
            if parsed.status in (A.PARTIAL, A.UNPARSED):
                unparsed_texts.append(record.text)
            for target in parsed.targets:
                if target.dataset:
                    datasets.add(target.dataset)
                else:
                    unresolved += 1
        annotated_items = len(annotated & distinct)
        return AnnotationMetrics(
            annotated_items=annotated_items,
            distinct_items=len(distinct),
            annotated_pct=(100.0 * annotated_items / len(distinct)) if distinct else None,
            form_annotations=by_level["form"],
            section_annotations=by_level["section"],
            concept_annotations=by_level["concept"],
            item_annotations=by_level["item"],
            codelist_item_annotations=by_level["codelist-item"],
            not_submitted=not_submitted,
            parsed=status[A.PARSED],
            partial=status[A.PARTIAL],
            unparsed=status[A.UNPARSED],
            unresolved_datasets=unresolved,
            datasets=sorted(datasets),
            unparsed_texts=list(dict.fromkeys(unparsed_texts)),
            unannotated_items=sorted(distinct - annotated),
        )

    @staticmethod
    def _form_metrics(design: StudyDesign) -> list:
        data = design.data
        annotated_by_form, not_submitted_by_form, domains_by_form = {}, Counter(), {}
        for record, parsed in design.parsed_annotations():
            if record.level in ("item", "codelist-item"):
                annotated_by_form.setdefault(record.form_oid, set()).add(record.item_oid)
            if parsed.not_submitted:
                not_submitted_by_form[record.form_oid] += 1
            for domain in parsed.domains:
                domains_by_form.setdefault(record.form_oid, []).append(domain)
        forms = []
        for form in design.forms:
            groups = [data.groups.get(row.oid) for row in design.groups_on(form)]
            forms.append(FormMetrics(
                oid=form, name=data.groups[form].name,
                domains=list(dict.fromkeys(domains_by_form.get(form, []))),
                sections=sum(1 for g in groups if g is not None and g.type == SECTION),
                concepts=sum(1 for g in groups if g is not None and g.type == CONCEPT),
                items=len(design.items_on(form)),
                annotated=len(annotated_by_form.get(form, set())),
                not_submitted=not_submitted_by_form[form],
                visits=len(design.form_visits.get(form, [])),
            ))
        return forms
