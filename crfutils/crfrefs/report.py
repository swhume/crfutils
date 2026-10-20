"""Report rendering for the crfrefs OID reference/definition checker.

Everything that turns a check result into words lives here so crfrefs.py stays about loading, traversal
and evaluation. This module imports nothing from crfrefs.py -- it duck-types the RefCheckResult it is
handed and reads severities through that object's errors and warnings properties -- which keeps the
dependency one-way and free of an import cycle.
"""
import json
from dataclasses import asdict
from textwrap import wrap

MODEL_LABELS = {"odm_2_0": "ODM v2.0"}

STRUCTURE_TEXT = {
    "form_nested": ("Form is referenced by another ItemGroupDef",
                    "Form ItemGroupDef '{oid}' is referenced by ItemGroupDef '{container}'"),
    "concept_contains_group": ("Concept references a {type}",
                               "Concept ItemGroupDef '{container}' references the {type} '{oid}'"),
    "event_references_non_form": ("StudyEventDef references a {type}, not a Form",
                                  "StudyEventDef '{container}' references ItemGroupDef '{oid}', a {type}, not a Form"),
    "form_not_scheduled": ("Form is not referenced by any StudyEventDef",
                           "Form ItemGroupDef '{oid}' is not referenced by any StudyEventDef"),
    "event_without_forms": ("StudyEventDef references no Form",
                            "StudyEventDef '{oid}' references no Form ItemGroupDef"),
}


def model_label(model_package: str) -> str:
    return MODEL_LABELS.get(model_package, model_package)


def article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def expected_text(allowed: tuple) -> str:
    """'ItemDef', or 'StudyEventDef or ItemGroupDef or ...' for an any-of reference"""
    return " or ".join(allowed)


def undefined_text(attribute: str, oid: str, allowed: tuple, document: bool, elsewhere: list) -> tuple:
    """
    phrasing for a reference to an OID (or, when document is True, a Leaf ID) that nothing defines in its
    MetaDataVersion; elsewhere lists the other MetaDataVersions that do define it
    :return: tuple of (detail for the text listing, self-contained message for the JSON report)
    """
    expected = expected_text(allowed)
    defines = "no Leaf defines this ID" if document else "no element defines this OID"
    if elsewhere:
        defines += " in its MetaDataVersion (it is defined only in MetaDataVersion " + ", ".join(elsewhere) + ")"
    detail = f"expects {article(expected)} {expected}; {defines}"
    return detail, f"{attribute} '{oid}' {detail}"


def mismatch_text(attribute: str, oid: str, allowed: tuple, actual: str) -> tuple:
    """
    phrasing for a reference that resolves to the wrong kind of element
    :return: tuple of (detail for the text listing, self-contained message for the JSON report)
    """
    expected = expected_text(allowed)
    detail = f"expects {article(expected)} {expected}, but {oid} is defined by {article(actual)} {actual}"
    return detail, f"{attribute} '{oid}' {detail}"


def duplicate_text(oid: str, definitions: list, scope) -> tuple:
    """
    phrasing for an OID defined more than once in one MetaDataVersion. Two ItemDefs under the same
    MetaDataVersion share a path, so each definition is named by element type and position among its
    siblings
    :param definitions: list of (element class name, ordinal) tuples in document order
    :return: tuple of (detail for the text listing, self-contained message for the JSON report)
    """
    first, rest = definitions[0], definitions[1:]
    detail = (f"defined by {first[0]} (#{first[1]}) and redefined by "
              + ", ".join(f"{element} (#{ordinal})" for element, ordinal in rest))
    where = f" in MetaDataVersion {scope}" if scope else ""
    return detail, f"OID '{oid}' is {detail}{where}"


def orphan_text(element: str, oid: str, via: list) -> tuple:
    """
    phrasing for a definition nothing references
    :param via: the reference attributes that could have referenced it
    :return: tuple of (detail for the text listing, self-contained message for the JSON report)
    """
    expected = f" (expected via {' or '.join(via)})" if via else ""
    return (f"{element} defined but never referenced{expected}",
            f"{element} '{oid}' is defined but never referenced{expected}")


def cycle_text(cycle: tuple) -> tuple:
    """phrasing for an ItemGroupRef chain that returns to an ancestor"""
    chain = " > ".join(cycle)
    return (f"ItemGroupRef chain {chain} returns to {cycle[-1]}; rendering would not terminate",
            f"ItemGroupDef '{cycle[-1]}' contains itself through the ItemGroupRef chain {chain}")


def structure_text(check: str, oid: str, container: str = None, type: str = None) -> tuple:
    """phrasing for the CRF-structure warnings"""
    detail, message = STRUCTURE_TEXT[check]
    values = {"oid": oid, "container": container, "type": type}
    return detail.format(**values), message.format(**values)


def render_text(result, errors_only: bool, max_locations: int) -> str:
    """
    builds the formatted text listing: header, notes, permissive banner, errors, warnings, summary
    :param result: the RefCheckResult to render
    :param errors_only: when True, the warnings are suppressed
    :param max_locations: max example locations shown per finding (0 shows all)
    :return: string
    """
    model = model_label(result.model_package)
    lines = ["ODM v2.0 OID reference/definition check",
             f"  File:  {result.crf_file}",
             f"  Model: {model} (odmlib {result.model_package}, odmlib {result.odmlib_version})",
             f"  Scope: {result.definition_count} definitions, {result.reference_count} "
             f"references across {len(result.checked_attributes)} checked attributes"]
    for note in result.notes:
        lines += ["", f"NOTE: {note}"]
    if result.permissive:
        lines += ["",
                  f"NOTE: loaded in permissive mode - this file is not conformant {model}.",
                  "      Results may be incomplete; run crfvalidate."]
    sections = [("ERRORS", result.errors), ("WARNINGS", [] if errors_only else result.warnings)]
    if not any(findings for _, findings in sections):
        lines += ["", "No OID reference/definition errors found." if errors_only
                  else "No OID reference/definition problems found."]
    for heading, findings in sections:
        if not findings:
            continue
        lines += ["", f"{heading} ({len(findings)})"]
        for finding in findings:
            lines += _render_finding(finding, max_locations)
    lines += [""] + _render_summary(result, errors_only)
    return "\n".join(lines)


def render_json(result, errors_only: bool, indent: int) -> str:
    """
    builds the JSON report; unlike the text listing it never truncates the locations
    :param result: the RefCheckResult to render
    :param errors_only: when True, the warnings are suppressed
    :param indent: JSON indent
    :return: string
    """
    warnings = [] if errors_only else result.warnings
    report = {
        "crf_file": result.crf_file,
        "model_package": result.model_package,
        "odmlib_version": result.odmlib_version,
        "permissive": result.permissive,
        "errors_only": errors_only,
        "counts": {
            "definitions": result.definition_count,
            "references": result.reference_count,
            "errors": len(result.errors),
            "warnings": len(warnings),
        },
        "findings": [asdict(f) for f in result.errors + warnings],
        "coverage": {
            "checked_attributes": result.checked_attributes,
            "skipped_attributes": result.skipped_attributes,
            "unchecked_elements": result.unchecked_elements,
            "unmapped_attributes": result.unmapped_attributes,
        },
        "notes": list(result.notes),
    }
    return json.dumps(report, indent=indent)


def _render_finding(finding, max_locations: int) -> list:
    """renders one finding: heading with the OID and occurrence count, detail, locations"""
    if finding.attribute:
        occurrences = len(finding.locations)
        count = f"   ({occurrences} occurrence{'s' if occurrences != 1 else ''})"
        heading = f"  {finding.check}  {finding.attribute} = \"{finding.oid}\"{count}"
    else:
        heading = f"  {finding.check}  {finding.oid}"
    lines = ["", heading, f"      {finding.detail}"]
    shown = finding.locations if max_locations <= 0 else finding.locations[:max_locations]
    for location in shown:
        lines.append(f"      - {location.element} in {location.path}")
    if len(finding.locations) > len(shown):
        lines.append(f"      ... and {len(finding.locations) - len(shown)} more")
    return lines


def _render_summary(result, errors_only: bool) -> list:
    """renders the closing tally and the coverage note that says what was and was not checked"""
    errors, warnings = len(result.errors), len(result.warnings)
    tally = f"  {errors} error{'s' if errors != 1 else ''}"
    if errors_only:
        tally += f" in {result.crf_file} (warnings suppressed)"
    else:
        tally += f", {warnings} warning{'s' if warnings != 1 else ''} in {result.crf_file}"
    lines = ["SUMMARY", tally]
    lines += _wrap_attributes("  Checked attributes: ", result.checked_attributes)
    lines += _wrap_attributes("  Skipped attributes: ", result.skipped_attributes)
    if result.skipped_attributes:
        lines.append(" " * 22 + "(file-level - not checked)")
    lines += _wrap_attributes("  Unchecked elements: ", result.unchecked_elements)
    if result.unchecked_elements:
        lines.append(" " * 22 + "(prior-version references are counted but not resolved)")
    if result.unmapped_attributes:
        lines += _wrap_attributes("  Unmapped attributes: ", result.unmapped_attributes)
        lines.append(" " * 23 + "(no definition class in the model - not checked)")
    return lines


def _wrap_attributes(label: str, attributes: list) -> list:
    text = label + (", ".join(attributes) if attributes else "none")
    return wrap(text, width=90, subsequent_indent=" " * len(label)) or [text]
