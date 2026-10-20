"""Report rendering for the crfvalidate schema validation checker.

Everything that turns a validation result into words lives here so validate.py stays about loading,
validating and grouping. This module imports nothing from validate.py -- it duck-types the
ValidationResult it is handed -- which keeps the dependency one-way and free of an import cycle. It
mirrors crfrefs/report.py so the two utilities read alike.
"""
import json
from dataclasses import asdict


def finding_text(element: str, reason: str) -> tuple:
    """
    phrasing for one schema validation error. The listing heading already names the check and the
    element, so the detail is the reason on its own; the JSON message repeats the element so each
    finding stands alone
    :return: tuple of (detail for the text listing, self-contained message for the JSON report)
    """
    return reason, f"{element}: {reason}"


def render_text(result, max_locations: int) -> str:
    """
    builds the formatted text listing: header, note, errors, summary
    :param result: the ValidationResult to render
    :param max_locations: max example locations shown per finding (0 shows all)
    :return: string
    """
    lines = ["ODM v2.0 schema validation",
             f"  File:   {result.crf_file}",
             f"  Schema: {result.schema_file}"]
    if result.findings:
        problems = len(result.findings)
        lines.append(f"  Scope:  {result.error_count} "
                     f"error{'s' if result.error_count != 1 else ''} in {problems} distinct "
                     f"problem{'s' if problems != 1 else ''}")
    if result.namespace_note:
        lines += ["", f"NOTE: {result.namespace_note}"]
    if result.findings:
        lines += ["", f"ERRORS ({len(result.findings)})"]
        for finding in result.findings:
            lines += _render_finding(finding, max_locations)
    else:
        lines += ["", "No schema validation errors found."]
    lines += [""] + _render_summary(result)
    return "\n".join(lines)


def render_json(result, indent: int) -> str:
    """
    builds the JSON report; unlike the text listing it never truncates the locations
    :param result: the ValidationResult to render
    :param indent: JSON indent
    :return: string
    """
    report = {
        "crf_file": result.crf_file,
        "schema_file": result.schema_file,
        "xmlschema_version": result.xmlschema_version,
        "root_namespace": result.root_namespace,
        "valid": result.is_valid,
        "counts": {
            "errors": result.error_count,
            "findings": len(result.findings),
        },
        "findings": [asdict(f) for f in result.findings],
        "notes": [result.namespace_note] if result.namespace_note else [],
    }
    return json.dumps(report, indent=indent)


def _render_finding(finding, max_locations: int) -> list:
    """renders one finding: heading with the element and occurrence count, reason, locations"""
    occurrences = len(finding.locations)
    count = f"   ({occurrences} occurrence{'s' if occurrences != 1 else ''})"
    lines = ["", f"  {finding.check}  {finding.element}{count}", f"      {finding.detail}"]
    shown = finding.locations if max_locations <= 0 else finding.locations[:max_locations]
    for location in shown:
        where = f"line {location.line}  " if location.line else ""
        lines.append(f"      - {where}{location.path}")
    if occurrences > len(shown):
        lines.append(f"      ... and {occurrences - len(shown)} more")
    return lines


def _render_summary(result) -> list:
    """renders the closing tally; the schema is repeated for anyone reading a long report bottom up"""
    errors = result.error_count
    lines = ["SUMMARY", f"  {errors} error{'s' if errors != 1 else ''} in {result.crf_file}"]
    if result.findings:
        lines.append(f"  Schema: {result.schema_file}")
    return lines
