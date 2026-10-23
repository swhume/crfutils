"""How a CRF item maps to SDTM beyond the text of its annotation, and the Define-XML Origin that suggests.

A data-definition tool needs three things the SDTM annotation alone does not give it:

- the CDASH mapping instructions (``Alias Context="mappingInstructions"``), classified by ``classify``:
  ``direct`` (maps directly to the SDTMIG target), ``concatenated`` (date and time components populate the
  SDTMIG --DTC variable the text names), ``relative_timing`` (the field may populate relative timing variables
  such as --STRF), ``split`` (numeric values go to one variable and text to another), ``not_submitted`` and
  ``other``. ``correct`` replaces an annotation's only target with the variable the instructions name when the
  two disagree (an annotation of AESTDAT whose instructions populate AESTDTC);
- the conditions a concept group implies: ``enrich`` adds the fixed value another item of the same Concept
  group assigns (``LBSPEC = BLOOD``) to the where clause of each value-level target (``LBORRES when LBTESTCD =
  PT``), with ``source="concept"``, so the target can be matched to a Define-XML where clause that has both;
- a proposed Origin, from ``propose``: Derived when the field feeds its targets indirectly (relative timing,
  the numeric/text split, or a NOT SUBMITTED field that names targets); else the ItemRef's Origin; else
  Collected with a placeholder source.

Pure Python like annotations.py, and like it never raises.
"""
import re
from dataclasses import dataclass, replace
from typing import Iterable, Union

from . import annotations as A

INSTRUCTIONS_CONTEXT = "mappingInstructions"
PLACEHOLDER = "__PLACEHOLDER__"

DIRECT, CONCATENATED, RELATIVE_TIMING, SPLIT, NOT_SUBMITTED, OTHER = (
    "direct", "concatenated", "relative_timing", "split", "not_submitted", "other")
# the kinds whose field feeds its targets through a rule rather than as collected
INDIRECT = (RELATIVE_TIMING, SPLIT)

# tried in order; the first that matches classifies the text. "does not map directly" (concatenated, relative
# timing) is not "does not map to an SDTMIG variable" (not submitted)
_KINDS = (
    (RELATIVE_TIMING, re.compile(r"\brelative timing variable", re.IGNORECASE)),
    (SPLIT, re.compile(r"\bnon-numeric\b|\bif numeric\b", re.IGNORECASE)),
    (CONCATENATED, re.compile(r"\bconcatenate", re.IGNORECASE)),
    (NOT_SUBMITTED, re.compile(r"\bnot submitted\b|\bdoes not map to an SDTM(?:IG)? variable", re.IGNORECASE)),
    (DIRECT, re.compile(r"^maps directly\b", re.IGNORECASE)),
)
# "populate the SDTMIG variable AESTDTC"; "the SDTMIG variable listed in ..." names none
_NAMED_RE = re.compile(rf"\bSDTM(?:IG)? variable ({A.DOMAIN_PATTERN})\b")

DERIVED, COLLECTED = "Derived", "Collected"
SPONSOR = "Sponsor"
# why propose() chose its origin
BASIS_INSTRUCTIONS, BASIS_NOT_SUBMITTED, BASIS_ITEMREF, BASIS_ANNOTATION = (
    "mappingInstructions", "not_submitted", "ItemRef/Origin", "annotation")


@dataclass(frozen=True)
class MappingInstruction:
    text: str
    kind: str                       # DIRECT | CONCATENATED | RELATIVE_TIMING | SPLIT | NOT_SUBMITTED | OTHER
    variables: tuple                # the SDTMIG variables the text names to populate, in order


@dataclass(frozen=True)
class ProposedOrigin:
    type: str                       # "Collected" | "Derived" | an ItemRef Origin/@Type
    source: str                     # an Origin/@Source, or PLACEHOLDER
    basis: str                      # BASIS_INSTRUCTIONS | BASIS_NOT_SUBMITTED | BASIS_ITEMREF | BASIS_ANNOTATION
    description: Union[str, None]   # PLACEHOLDER for a Derived origin: the derivation is not on the CRF


def instructions_text(aliases: Iterable) -> Union[str, None]:
    """the text of an ItemDef's mappingInstructions alias (the XSD allows one per context), or None"""
    return next((alias.name for alias in aliases if alias.context == INSTRUCTIONS_CONTEXT), None)


def classify(text: Union[str, None]) -> Union[MappingInstruction, None]:
    """the kind of a mapping instruction and the variables it names; None for no text or a placeholder"""
    normalized = A.normalize(text)
    if not normalized or normalized == PLACEHOLDER:
        return None
    kind = next((kind for kind, pattern in _KINDS if pattern.search(normalized)), OTHER)
    return MappingInstruction(normalized, kind, tuple(dict.fromkeys(_NAMED_RE.findall(normalized))))


def correct(parsed: A.ParsedAnnotation, instruction: Union[MappingInstruction, None],
            context_domain: Union[str, None] = None, known_domains: Iterable[str] = ()) -> tuple:
    """
    checks an item annotation against its mapping instructions. When the instructions name the SDTMIG
    variable to populate and the annotation's only target is a different variable, the target becomes the
    named one, with variable_source "mappingInstructions" and its dataset resolved again. Any other
    disagreement -- several targets, none of them named; instructions that say the field is not submitted
    while the annotation names targets -- leaves the annotation as it is
    :return: (ParsedAnnotation, a description of the disagreement or None)
    """
    if instruction is None or not parsed.targets:
        return parsed, None
    variables = [t.qnam or t.variable for t in parsed.targets]
    if instruction.kind == NOT_SUBMITTED and not parsed.not_submitted:
        return parsed, (f"the mapping instructions say the field is not submitted, but the SDTM annotation names "
                        f"{', '.join(variables)}")
    named = instruction.variables
    if not named or set(variables) & set(named):
        return parsed, None
    described = f"the SDTM annotation names {', '.join(variables)}; the mapping instructions name {', '.join(named)}"
    old = parsed.targets[0]
    if len(named) > 1 or len(parsed.targets) > 1 or old.qnam is not None:
        return parsed, described
    qualified = old.dataset if old.dataset_source == "qualified" else None
    dataset, source = A.resolve_dataset(named[0], qualified, context_domain, known_domains)
    new = replace(old, dataset=dataset, dataset_source=source, variable=named[0],
                  key=A.target_key(dataset, named[0], old.where), variable_source=INSTRUCTIONS_CONTEXT)
    return replace(parsed, targets=(new,)), described


def enrich(annotations: list, concepts: Iterable[str]) -> list:
    """
    adds to each value-level target the fixed values the other items of its Concept group assign. A fixed
    value is an item annotation's `VAR = VALUE` target with no where clause of its own (``LBSPEC = BLOOD``);
    it becomes the condition `VAR EQ VALUE` (source "concept") of every target in the same group that already
    has a where clause, is in the same dataset and does not test VAR. A variable given two different values
    in the group implies nothing
    :param annotations: (record, ParsedAnnotation) pairs; a record has level, group_path and item_oid
    :param concepts: the OIDs of the Concept ItemGroupDefs
    :return: the ParsedAnnotations in the same order, enriched
    """
    concepts = set(concepts)
    fixed = {}                      # group path -> {(dataset, variable): {(value, item_oid)}}
    for record, parsed in annotations:
        if record.level != "item" or parsed.not_submitted or not record.group_path \
                or record.group_path[-1] not in concepts:
            continue
        for target in parsed.targets:
            if target.value is not None and not target.where and target.dataset and target.qnam is None:
                fixed.setdefault(record.group_path, {}).setdefault(
                    (target.dataset, target.variable), set()).add((target.value, record.item_oid))
    enriched = []
    for record, parsed in annotations:
        group = fixed.get(record.group_path)
        if not group or not any(target.where for target in parsed.targets):
            enriched.append(parsed)
            continue
        targets = []
        for target in parsed.targets:
            if target.where:
                tested = {c.variable for c in target.where} | {target.variable}
                added = []
                for (dataset, variable), assigned in group.items():
                    values = {value for value, item in assigned if item != record.item_oid}
                    if dataset == target.dataset and variable not in tested and len(values) == 1:
                        added.append(A.Condition(variable, "EQ", (values.pop(),), source="concept"))
                if added:
                    where = target.where + tuple(added)
                    target = replace(target, where=where, key=A.target_key(target.dataset, target.variable, where))
            targets.append(target)
        enriched.append(replace(parsed, targets=tuple(targets)))
    return enriched


def propose(parsed: A.ParsedAnnotation, instruction: Union[MappingInstruction, None] = None,
            origins: Iterable = ()) -> Union[ProposedOrigin, None]:
    """
    the Origin an annotation suggests for its targets; None when it names none.
    - Derived (Sponsor) when the field feeds its targets indirectly: the mapping instructions say relative
      timing or a numeric/text split, or the annotation is NOT SUBMITTED yet names targets;
    - else the first ItemRef Origin with a Type (date and time concatenated into --DTC stay as collected);
    - else Collected, with a placeholder source: an annotated field is collected, but the CRF does not say by whom.
    A Derived origin's description is a placeholder: the derivation is not on the CRF
    :param origins: the ItemRef's Origins (type, source)
    """
    if not parsed.targets:
        return None
    if instruction is not None and instruction.kind in INDIRECT:
        return ProposedOrigin(DERIVED, SPONSOR, BASIS_INSTRUCTIONS, PLACEHOLDER)
    if parsed.not_submitted:
        return ProposedOrigin(DERIVED, SPONSOR, BASIS_NOT_SUBMITTED, PLACEHOLDER)
    for origin in origins:
        if origin.type:
            return ProposedOrigin(origin.type, origin.source or PLACEHOLDER, BASIS_ITEMREF,
                                  PLACEHOLDER if origin.type == DERIVED else None)
    return ProposedOrigin(COLLECTED, PLACEHOLDER, BASIS_ANNOTATION, None)
