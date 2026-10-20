"""The study design of an ODM v2.0 CRF, independent of how the document was read.

``DesignData`` is the plain data two extractors fill: ``_odm.design_from_lxml`` (crfhtml, crfpdf) and
``_model.design_from_model`` (crfrefs, crfmetrics). A test asserts they are equal on every fixture.
``StudyDesign`` derives what the utilities share from it: the form order, the visit schedule, the walk
of a form's rows (the rows crfhtml renders), group domains and the annotation records.

This module imports neither lxml nor odmlib.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Iterator, Union

from . import annotations as A

# the ItemGroupDef types a CRF is built from; any other Type is walked and rendered as a section
FORM, SECTION, CONCEPT = "Form", "Section", "Concept"
# recursion cap on nested ItemGroupRefs, shared with the stylesheet (group-rows' $depth test)
MAX_DEPTH = 10

# where a group-level annotation comes from, by level; the Alias contexts are vocabularies A and B
FORM_CONTEXTS = ("formAnnotation", "SDTM")
SECTION_CONTEXTS = ("formSectionAnnotation", "SDTM")
CONCEPT_CONTEXTS = ("SDTM",)
ITEM_CONTEXT = "SDTM"


@dataclass(frozen=True)
class Alias:
    context: str
    name: str


@dataclass(frozen=True)
class ChildRef:
    kind: str                       # "ItemRef" | "ItemGroupRef" | "StudyEventRef" | "StudyEventGroupRef"
    oid: str                        # the referenced OID
    order: Union[int, None]         # @OrderNumber
    mandatory: Union[str, None]     # @Mandatory, "Yes" | "No"


@dataclass(frozen=True)
class GroupDef:
    oid: str
    name: str
    type: Union[str, None]          # "Form" | "Section" | "Concept" | ...
    domain: Union[str, None]        # @Domain
    aliases: tuple                  # Alias, in document order
    children: tuple                 # ChildRef (ItemRef | ItemGroupRef), in document order
    description: Union[str, None] = None


@dataclass(frozen=True)
class ItemDef:
    oid: str
    name: str
    datatype: Union[str, None]
    length: Union[int, None]
    aliases: tuple
    codelist_oid: Union[str, None]
    question: Union[str, None] = None
    prompt: Union[str, None] = None


@dataclass(frozen=True)
class CodeListItem:
    coded_value: str
    decode: Union[str, None]
    aliases: tuple


@dataclass(frozen=True)
class CodeList:
    oid: str
    name: str
    items: tuple                    # CodeListItem, in document order


@dataclass(frozen=True)
class EventDef:
    oid: str
    name: str
    type: Union[str, None]          # "Scheduled" | "Unscheduled" | "Common"
    forms: tuple                    # ChildRef (ItemGroupRef), in document order


@dataclass(frozen=True)
class EventGroupDef:
    oid: str
    name: str
    children: tuple                 # ChildRef (StudyEventRef | StudyEventGroupRef), in document order


@dataclass(frozen=True)
class Leaf:
    id: str
    href: Union[str, None]
    title: Union[str, None]


@dataclass
class DesignData:
    """the first Study/MetaDataVersion of a document, as plain data; dicts keep document order"""
    study_oid: Union[str, None] = None
    study_name: Union[str, None] = None
    protocol_name: Union[str, None] = None
    mdv_oid: Union[str, None] = None
    mdv_name: Union[str, None] = None
    mdv_description: Union[str, None] = None
    groups: dict = field(default_factory=OrderedDict)         # oid -> GroupDef
    items: dict = field(default_factory=OrderedDict)          # oid -> ItemDef
    codelists: dict = field(default_factory=OrderedDict)      # oid -> CodeList
    events: dict = field(default_factory=OrderedDict)         # oid -> EventDef
    event_groups: dict = field(default_factory=OrderedDict)   # oid -> EventGroupDef
    protocol: tuple = ()                                      # ChildRef (StudyEventGroupRef)
    acrf_leaf: Union[Leaf, None] = None                       # the AnnotatedCRF's Leaf, when present


@dataclass(frozen=True)
class Node:
    """one row of a rendered form: a group heading or an item"""
    kind: str                       # "group" | "item"
    oid: str
    path: tuple                     # the group OIDs from the form down to the containing group
    mandatory: Union[str, None]
    order: Union[int, None]

    @property
    def depth(self) -> int:
        return len(self.path) - 1


@dataclass(frozen=True)
class AnnotationRecord:
    """one annotation as rendered: the same fields the HTML carries in its data-* attributes"""
    level: str                      # "form" | "section" | "concept" | "item" | "codelist-item"
    source: str                     # "alias:SDTM" | "alias:formAnnotation" | ... | "attr:Domain"
    text: str
    form_oid: str
    group_path: tuple               # the group OIDs from the form down to the annotated group
    item_oid: Union[str, None] = None
    codelist_oid: Union[str, None] = None
    coded_value: Union[str, None] = None


def sort_key(child: ChildRef) -> tuple:
    """
    the order children render in: by OrderNumber, with children that have none first, and document
    order among equals. This is what the stylesheet's <xsl:sort data-type="number"/> does: a missing
    OrderNumber is NaN, which sorts before every number, and XSLT sorting is stable
    """
    return (0, 0) if child.order is None else (1, child.order)


def level_of(group_type: Union[str, None]) -> str:
    """the annotation level of an ItemGroupDef type"""
    if group_type == FORM:
        return "form"
    if group_type == CONCEPT:
        return "concept"
    return "section"


class StudyDesign:
    """
    what the utilities share about a CRF's structure: the forms in display order, the visit schedule,
    the walk of each form's rows, group domains and the annotation records. Built from DesignData by
    either extractor
    """

    def __init__(self, data: DesignData) -> None:
        self.data = data
        self.cycles = []            # tuples of group OIDs, each ending with the OID that repeats
        self.too_deep = []          # tuples of group OIDs where the recursion cap stopped the walk
        self.visits = self._visit_order()
        self.schedule = self._schedule()
        self.has_schedule = any(self.schedule.values())
        self.form_visits = self._form_visits()
        self.forms = self._form_order()
        self._walks = {}
        self._known_domains = None

    # --- forms and visits --------------------------------------------------------------------------

    @property
    def form_groups(self) -> list:
        """the Form ItemGroupDefs in document order"""
        return [g for g in self.data.groups.values() if g.type == FORM]

    def _visit_order(self) -> list:
        """
        StudyEventDef OIDs in schedule order: the Protocol's StudyEventGroupRefs, each expanded through
        its StudyEventGroupDef recursively, sorting by OrderNumber then document order; then any
        StudyEventGroupDef the protocol did not reach, in document order; then any StudyEventDef not
        reached, in document order
        """
        order, seen_groups = [], set()

        def expand(group_oid: str) -> None:
            group = self.data.event_groups.get(group_oid)
            if group is None or group_oid in seen_groups:
                return
            seen_groups.add(group_oid)
            for child in sorted(group.children, key=sort_key):
                if child.kind == "StudyEventRef":
                    if child.oid in self.data.events and child.oid not in order:
                        order.append(child.oid)
                else:
                    expand(child.oid)

        for ref in sorted(self.data.protocol, key=sort_key):
            expand(ref.oid)
        for group_oid in self.data.event_groups:
            expand(group_oid)
        for event_oid in self.data.events:
            if event_oid not in order:
                order.append(event_oid)
        return order

    def _schedule(self) -> dict:
        """visit OID -> [ChildRef] of the Form ItemGroupDefs it collects, in OrderNumber order"""
        schedule = OrderedDict()
        for visit in self.visits:
            refs = [ref for ref in sorted(self.data.events[visit].forms, key=sort_key)
                    if self.data.groups.get(ref.oid) is not None
                    and self.data.groups[ref.oid].type == FORM]
            schedule[visit] = refs
        return schedule

    def _form_visits(self) -> dict:
        """form OID -> [visit OIDs] in visit order"""
        visits = OrderedDict((g.oid, []) for g in self.form_groups)
        for visit, refs in self.schedule.items():
            for ref in refs:
                if ref.oid in visits and visit not in visits[ref.oid]:
                    visits[ref.oid].append(visit)
        return visits

    def _form_order(self) -> list:
        """
        the Form OIDs in display order: by first appearance in the visit schedule when there is one,
        then the unscheduled forms in document order; document order when there is no schedule
        """
        order = []
        if self.has_schedule:
            for refs in self.schedule.values():
                for ref in refs:
                    if ref.oid not in order:
                        order.append(ref.oid)
        for group in self.form_groups:
            if group.oid not in order:
                order.append(group.oid)
        return order

    @property
    def unscheduled_forms(self) -> list:
        """Form OIDs no StudyEventDef collects, meaningful only when has_schedule"""
        return [oid for oid, visits in self.form_visits.items() if not visits]

    @property
    def events_without_forms(self) -> list:
        """StudyEventDef OIDs with no ItemGroupRef to a Form"""
        return [visit for visit, refs in self.schedule.items() if not refs]

    def mandatory(self, visit: str, form: str) -> Union[str, None]:
        """the Mandatory value of a form in a visit, or None when the visit does not collect it"""
        for ref in self.schedule.get(visit, []):
            if ref.oid == form:
                return ref.mandatory
        return None

    # --- the walk ----------------------------------------------------------------------------------

    def children(self, group_oid: str) -> list:
        """a group's ItemRef and ItemGroupRef children in render order"""
        group = self.data.groups.get(group_oid)
        return [] if group is None else sorted(group.children, key=sort_key)

    def walk(self, form_oid: str) -> list:
        """
        the rows of a form in render order: a Node per nested group heading and per item occurrence.
        A group that is its own ancestor is recorded in cycles and not entered; nesting deeper than
        MAX_DEPTH is recorded in too_deep and not entered. Cached per form
        """
        if form_oid not in self._walks:
            rows = []
            self._walk(form_oid, (form_oid,), rows)
            self._walks[form_oid] = rows
        return self._walks[form_oid]

    def _walk(self, group_oid: str, path: tuple, rows: list) -> None:
        for child in self.children(group_oid):
            if child.kind == "ItemRef":
                rows.append(Node("item", child.oid, path, child.mandatory, child.order))
                continue
            # every nested group gets a heading row, as the stylesheet renders one; a group that is its own
            # ancestor, one nested too deeply, and a dangling ItemGroupRef (crfrefs reports it) are not entered
            rows.append(Node("group", child.oid, path + (child.oid,), child.mandatory, child.order))
            if child.oid in path:
                self.cycles.append(path + (child.oid,))
            elif len(path) > MAX_DEPTH:
                self.too_deep.append(path + (child.oid,))
            elif child.oid in self.data.groups:
                self._walk(child.oid, path + (child.oid,), rows)

    def items_on(self, form_oid: str) -> list:
        """the item occurrences of a form, in render order"""
        return [row for row in self.walk(form_oid) if row.kind == "item"]

    def groups_on(self, form_oid: str) -> list:
        """the nested group headings of a form, in render order"""
        return [row for row in self.walk(form_oid) if row.kind == "group"]

    # --- annotations -------------------------------------------------------------------------------

    def group_annotations(self, group_oid: str) -> list:
        """
        the (source, text) annotations of a group, by its type: a Form's formAnnotation or SDTM aliases,
        a Section's formSectionAnnotation or SDTM aliases, a Concept's SDTM aliases; when a Form or
        Section has none, its @Domain
        """
        group = self.data.groups.get(group_oid)
        if group is None:
            return []
        contexts = {FORM: FORM_CONTEXTS, CONCEPT: CONCEPT_CONTEXTS}.get(group.type, SECTION_CONTEXTS)
        found = [(f"alias:{alias.context}", alias.name) for alias in group.aliases
                 if alias.context in contexts and alias.name is not None]
        if not found and group.type != CONCEPT and group.domain:
            found.append(("attr:Domain", group.domain))
        return found

    def completion_instructions(self, group_oid: str) -> list:
        """a group's completion-instruction aliases (vocabularies A and B)"""
        group = self.data.groups.get(group_oid)
        if group is None:
            return []
        return [alias.name for alias in group.aliases
                if alias.context in ("formSectionCompletionInstruction", "completionInstructions")]

    def group_domain(self, group_oid: str) -> Union[str, None]:
        """the first domain a group's annotations name, or None"""
        for source, text in self.group_annotations(group_oid):
            parsed = A.parse(text, level="group", source=source)
            if parsed.domains:
                return parsed.domains[0]
        return None

    def context_domain(self, group_path: tuple) -> Union[str, None]:
        """the domain of the innermost group on a path that names one"""
        for group_oid in reversed(group_path):
            domain = self.group_domain(group_oid)
            if domain:
                return domain
        return None

    @property
    def known_domains(self) -> frozenset:
        """
        every domain the document names: in group annotations, as the dataset of a qualified variable,
        and the domain a SUPPxx annotation supplements. Used to tell a bare domain from a variable and
        to infer a variable's dataset from its prefix
        """
        if self._known_domains is None:
            domains = set()
            for group in self.data.groups.values():
                domain = self.group_domain(group.oid)
                if domain:
                    domains.add(domain)
            for record in self.annotations():
                if record.level in ("item", "codelist-item"):
                    domains.update(A.datasets_named(record.text))
            self._known_domains = frozenset(domains)
        return self._known_domains

    def annotations(self) -> list:
        """
        every annotation the rendered CRF shows, form by form in display order: the same records, with
        the same fields, that the HTML carries in its data-* attributes, so the two can be compared
        """
        records = []
        for form_oid in self.forms:
            for source, text in self.group_annotations(form_oid):
                records.append(AnnotationRecord("form", source, text, form_oid, (form_oid,)))
            for row in self.walk(form_oid):
                if row.kind == "group":
                    group = self.data.groups.get(row.oid)
                    level = level_of(group.type) if group is not None else "section"
                    for source, text in self.group_annotations(row.oid):
                        records.append(AnnotationRecord(level, source, text, form_oid, row.path))
                    continue
                item = self.data.items.get(row.oid)
                if item is None:
                    continue
                for alias in item.aliases:
                    if alias.context == ITEM_CONTEXT and alias.name is not None:
                        records.append(AnnotationRecord("item", f"alias:{ITEM_CONTEXT}", alias.name,
                                                        form_oid, row.path, item_oid=item.oid))
                codelist = self.data.codelists.get(item.codelist_oid) if item.codelist_oid else None
                if codelist is None:
                    continue
                for cli in codelist.items:
                    for alias in cli.aliases:
                        if alias.context == ITEM_CONTEXT and alias.name is not None:
                            records.append(AnnotationRecord(
                                "codelist-item", f"alias:{ITEM_CONTEXT}", alias.name, form_oid, row.path,
                                item_oid=item.oid, codelist_oid=codelist.oid, coded_value=cli.coded_value))
        return records

    def parsed_annotations(self) -> Iterator[tuple]:
        """(AnnotationRecord, ParsedAnnotation) pairs, each parsed with its context domain"""
        known = self.known_domains
        for record in self.annotations():
            level = "group" if record.level in ("form", "section", "concept") else "item"
            yield record, A.parse(record.text, level=level, source=record.source,
                                  context_domain=self.context_domain(record.group_path), known_domains=known)
