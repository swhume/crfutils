"""The SDTM annotation grammar: parses the text of a CRF annotation into datasets and variables.

Annotation text is free text in practice, so this parser is deliberately lenient and never raises. It
reads the forms found in real ODM v2.0 CRFs:

- domains: ``DOMAIN = VS``, ``VS (Vital Signs)``, ``VS = Vital Signs``, a bare ``VS``, ``SUPPVS``;
- targets: ``VSORRES``, ``DM.SEX=M``, ``VSORRESU = mmHg when VSTESTCD = SYSBP``,
  ``RSSTRESN/RSSTRESC where RSTESTCD=ATLAS101``, ``FTASTDEV in SUPPFT``;
- several targets in one annotation, separated by ``;``: ``CMDOSE;CMDOSTXT``;
- ``[NOT SUBMITTED]``, alone or with targets;
- at Concept level, a concept's fixed values: ``VSTESTCD = SYSBP; VSTEST = Systolic Blood Pressure`` are targets
  (a ``NAME = VALUE`` whose name has a known-domain prefix), not domain labels like ``VS = Vital Signs``.

Anything it cannot read is kept verbatim in ``unparsed`` with a warning.

The key (``target_key``) -- ``DATASET.VARIABLE[ where VAR = VALUE[ and ...]]`` -- is a public contract:
the page-references JSON crfpdf writes is indexed by it, and the Define-XML consumer builds the same key
from its ValueListDef/WhereClauseDef metadata. Change it only with a bump of the JSON schema_version.
"""
import re
from dataclasses import dataclass, field
from typing import Iterable, Union

DOMAIN_PATTERN = r"[A-Z][A-Z0-9]{1,7}"
VARIABLE_PATTERN = r"[A-Z][A-Z0-9_]{0,39}"
_QUALIFIED = rf"(?:{DOMAIN_PATTERN}\.)?{VARIABLE_PATTERN}"

_DOMAIN_RE = re.compile(rf"^{DOMAIN_PATTERN}$")
_SUPP_RE = re.compile(r"^SUPP[A-Z0-9]{1,4}$")
_NOT_SUBMITTED_RE = re.compile(r"^\[?\s*NOT\s+SUBMITTED\s*\]?\s*[:,-]?\s*(.*)$", re.IGNORECASE)
_DOMAIN_EQ_RE = re.compile(rf"^DOMAIN\s*=\s*({DOMAIN_PATTERN})$")
_DOMAIN_LABEL_RE = re.compile(rf"^({DOMAIN_PATTERN})\s*(?:\((.*)\)|=\s*(.+))$")
_VARLIST_RE = re.compile(rf"^({_QUALIFIED}(?:\s*/\s*{_QUALIFIED})*)$")
_IN_SUPP_RE = re.compile(r"^(.*?)\s+in\s+(SUPP[A-Z0-9]{1,4})$", re.IGNORECASE)
_CONDITION_SPLIT_RE = re.compile(r"\s+(?:when|where|if)\s+", re.IGNORECASE)
_AND_RE = re.compile(r"\s+and\s+", re.IGNORECASE)
_CONDITION_RE = re.compile(rf"^({_QUALIFIED})\s*(==|=|!=|<>|EQ|NE|IN)\s*(.+)$", re.IGNORECASE)
_QUOTED_RE = re.compile(r"""^(['"])(.*)\1$""")
_WHITESPACE_RE = re.compile(r"\s+")

# the word "ALL" matches the domain pattern but is never a domain
NOT_DOMAINS = {"ALL"}

PARSED, PARTIAL, UNPARSED, EMPTY = "parsed", "partial", "unparsed", "empty"
DATASET_UNRESOLVED = "dataset_unresolved"
UNPARSED_TEXT = "unparsed_text"
UNPARSED_CONDITION = "unparsed_condition"


@dataclass(frozen=True)
class Condition:
    variable: str
    comparator: str                 # "EQ" | "NE" | "IN"
    values: tuple                   # the compared values; one for EQ and NE
    source: str = "annotation"      # "annotation" | "concept" (added by mapping.enrich from a sibling item)


@dataclass(frozen=True)
class Target:
    dataset: Union[str, None]       # None when it could not be resolved
    dataset_source: Union[str, None]    # "qualified" | "supp" | "prefix" | "context" | None
    variable: str
    value: Union[str, None]         # the value a `VAR = VALUE` annotation assigns
    where: tuple                    # Condition
    qnam: Union[str, None]          # for `X in SUPPxx`: X
    key: str                        # target_key(dataset, variable, where)
    variable_source: str = "annotation"     # "annotation" | "mappingInstructions" (set by mapping.correct)
    define_item_oid: Union[str, None] = None    # the Define-XML ItemDef the CRF pairs it with (SDTMItemOIDs)


@dataclass
class ParsedAnnotation:
    text: str
    status: str                     # "parsed" | "partial" | "unparsed" | "empty"
    not_submitted: bool = False
    domains: tuple = ()             # the domains the annotation names, in order
    targets: tuple = ()             # Target
    unparsed: tuple = ()            # the segments that could not be read
    warnings: tuple = ()            # warning codes


def normalize(text: str) -> str:
    """collapses whitespace"""
    return _WHITESPACE_RE.sub(" ", text or "").strip()


def _unquote(value: str) -> str:
    value = value.strip()
    match = _QUOTED_RE.match(value)
    return match.group(2) if match else value


def _split_qualified(name: str) -> tuple:
    """('DM', 'SEX') for DM.SEX; (None, 'SEX') for SEX"""
    if "." in name:
        dataset, variable = name.split(".", 1)
        return dataset, variable
    return None, name


def condition_text(condition: Condition) -> str:
    """one condition as the key renders it"""
    if condition.comparator == "IN":
        return f"{condition.variable} IN ({', '.join(sorted(condition.values))})"
    value = condition.values[0] if condition.values else ""
    return f"{condition.variable} {'=' if condition.comparator == 'EQ' else 'NE'} {value}"


def target_key(dataset: Union[str, None], variable: str, where: Iterable[Condition] = ()) -> str:
    """
    the public key of a target: DATASET.VARIABLE[ where COND[ and COND...]], conditions sorted by
    variable. An unresolved dataset gives the bare variable
    """
    key = f"{dataset}.{variable}" if dataset else variable
    conditions = sorted(where, key=lambda c: (c.variable, c.comparator))
    if conditions:
        key += " where " + " and ".join(condition_text(c) for c in conditions)
    return key


def _parse_conditions(text: str) -> Union[tuple, None]:
    """the conditions of a when/where/if clause, or None when the clause cannot be read"""
    conditions = []
    for clause in _AND_RE.split(text):
        match = _CONDITION_RE.match(clause.strip())
        if match is None:
            return None
        variable, comparator, value = match.group(1), match.group(2).upper(), match.group(3).strip()
        _, variable = _split_qualified(variable)
        if comparator == "IN":
            if value.startswith("(") and value.endswith(")"):
                value = value[1:-1]
            values = tuple(_unquote(v) for v in value.split(",") if v.strip())
            conditions.append(Condition(variable, "IN", values))
        elif comparator in ("!=", "<>", "NE"):
            conditions.append(Condition(variable, "NE", (_unquote(value),)))
        else:
            conditions.append(Condition(variable, "EQ", (_unquote(value),)))
    return tuple(conditions)


def annotation_key(target: Target) -> str:
    """the key of a target from the annotation's own conditions, without those mapping.enrich added"""
    return target_key(target.dataset, target.variable, [c for c in target.where if c.source == "annotation"])


def resolve_dataset(variable: str, qualified: Union[str, None], context_domain: Union[str, None],
                    known_domains: Iterable[str]) -> tuple:
    """(dataset, source): qualified, then the longest known domain that is a strict prefix of the
    variable, then the context domain; (None, None) when nothing applies"""
    if qualified:
        return qualified, "qualified"
    prefixes = [d for d in known_domains if variable.startswith(d) and len(variable) > len(d)]
    if prefixes:
        return max(prefixes, key=len), "prefix"
    if context_domain:
        return context_domain, "context"
    return None, None


def datasets_named(text: str) -> set:
    """
    the domains an item-level annotation names outright: the dataset of a qualified variable and the
    domain a SUPPxx supplements. Used to collect a document's known domains before parsing
    """
    found = set()
    for segment in normalize(text).split(";"):
        segment = segment.strip()
        match = _NOT_SUBMITTED_RE.match(segment)
        if match:
            segment = match.group(1).strip()
        supp = _IN_SUPP_RE.match(segment)
        if supp:
            found.add(supp.group(2).upper()[4:])
            segment = supp.group(1)
        head = _CONDITION_SPLIT_RE.split(segment, maxsplit=1)[0]
        head = head.split("=", 1)[0].strip()
        for name in re.split(r"\s*/\s*", head):
            dataset, _ = _split_qualified(name)
            if dataset and _DOMAIN_RE.match(dataset):
                found.add(dataset)
    return found


def parse(text: str, level: str = "item", source: Union[str, None] = None,
          context_domain: Union[str, None] = None,
          known_domains: Iterable[str] = ()) -> ParsedAnnotation:
    """
    parses one annotation. Never raises
    :param text: the annotation text
    :param level: "group" for a form or section annotation; "concept" for a concept annotation, which reads
        `NAME = VALUE` as a target when NAME has a known-domain prefix; "item" for an item or codelist item
    :param source: where the text came from; an "attr:Domain" value is a domain as it stands
    :param context_domain: the domain of the innermost enclosing group, for an unqualified variable
    :param known_domains: the domains the document names, for the prefix rule and for telling a bare
        domain from a variable at item level
    :return: ParsedAnnotation
    """
    known = frozenset(known_domains)
    result = ParsedAnnotation(text=text or "", status=EMPTY)
    normalized = normalize(text)
    if source == "attr:Domain":
        # an ItemGroupDef/@Domain is a domain as it stands, when it looks like one (Result_ODMv2.xml
        # has Domain="all" on a common section, which is not a dataset)
        if _DOMAIN_RE.match(normalized) and normalized not in NOT_DOMAINS:
            result.domains, result.status = (normalized,), PARSED
        elif normalized:
            result.unparsed, result.warnings, result.status = (normalized,), (UNPARSED_TEXT,), UNPARSED
        return result
    domains, targets, unparsed, warnings = [], [], [], []
    for segment in normalized.split(";"):
        segment = segment.strip()
        if not segment:
            continue
        match = _NOT_SUBMITTED_RE.match(segment)
        if match:
            result.not_submitted = True
            segment = match.group(1).strip()
            if not segment:
                continue
        domain = _parse_domain(segment, level, known)
        if domain:
            domains.append(domain)
            continue
        parsed = _parse_target(segment, context_domain, known, warnings)
        if parsed is None:
            unparsed.append(segment)
            warnings.append(UNPARSED_TEXT)
        else:
            targets.extend(parsed)
    result.domains, result.targets = tuple(domains), tuple(targets)
    result.unparsed, result.warnings = tuple(unparsed), tuple(dict.fromkeys(warnings))
    if targets or domains:
        result.status = PARTIAL if unparsed else PARSED
    elif unparsed:
        result.status = UNPARSED
    elif result.not_submitted:
        result.status = PARSED
    return result


def _has_domain_prefix(name: str, known: frozenset) -> bool:
    """whether a known domain is a strict prefix of the name, as for a variable (VSTESTCD and VS)"""
    return any(name.startswith(domain) and len(name) > len(domain) for domain in known)


def _parse_domain(segment: str, level: str, known: frozenset) -> Union[str, None]:
    """the domain a segment names, or None when it is not a domain form"""
    match = _DOMAIN_EQ_RE.match(segment)
    if match:
        return match.group(1)
    if _SUPP_RE.match(segment):
        return segment
    group_level = level in ("group", "concept")
    # at Concept level `VSTESTCD = SYSBP` fixes a variable's value: a target, not a domain label
    fixed_value = level == "concept"
    match = _DOMAIN_LABEL_RE.match(segment)
    if match and group_level and match.group(1) not in NOT_DOMAINS:
        if not (fixed_value and match.group(3) is not None and _has_domain_prefix(match.group(1), known)):
            return match.group(1)
    if _DOMAIN_RE.match(segment) and segment not in NOT_DOMAINS:
        # at group level a bare token is a domain; at item level only a known domain is
        if (group_level and not (fixed_value and _has_domain_prefix(segment, known))) or segment in known:
            return segment
    return None


def _parse_target(segment: str, context_domain: Union[str, None], known: frozenset,
                  warnings: list) -> Union[list, None]:
    """the targets of `VARLIST [= VALUE] [when COND] [in SUPPxx]`, or None when it is not one"""
    supp = None
    match = _IN_SUPP_RE.match(segment)
    if match:
        segment, supp = match.group(1).strip(), match.group(2).upper()
    parts = _CONDITION_SPLIT_RE.split(segment, maxsplit=1)
    head, clause = parts[0].strip(), (parts[1].strip() if len(parts) > 1 else None)
    value = None
    if "=" in head:
        head, value = head.split("=", 1)
        head, value = head.strip(), _unquote(value)
    match = _VARLIST_RE.match(head)
    if match is None:
        return None
    where = ()
    if clause is not None:
        conditions = _parse_conditions(clause)
        if conditions is None:
            warnings.append(UNPARSED_CONDITION)
        else:
            where = conditions
    targets = []
    for name in re.split(r"\s*/\s*", head):
        qualified, variable = _split_qualified(name)
        if supp:
            dataset, source = supp, "supp"
            conditions = (Condition("QNAM", "EQ", (variable,)),) + where
            targets.append(Target(dataset, source, "QVAL", value, conditions, variable,
                                  target_key(dataset, "QVAL", conditions)))
            continue
        dataset, source = resolve_dataset(variable, qualified, context_domain, known)
        if dataset is None:
            warnings.append(DATASET_UNRESOLVED)
        targets.append(Target(dataset, source, variable, value, where, None,
                              target_key(dataset, variable, where)))
    return targets
