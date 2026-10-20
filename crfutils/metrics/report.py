"""Report rendering for the crfmetrics module.

Everything that turns a metrics result into words lives here so metrics.py stays about loading, walking
the model and counting. This module imports nothing from metrics.py -- it duck-types the MetricsResult
it is handed -- which keeps the dependency one-way and free of an import cycle, exactly as
crfrefs/report.py and validate/report.py do.
"""
import json
from dataclasses import asdict
from textwrap import wrap

MODEL_LABELS = {"odm_2_0": "ODM v2.0"}
SECTION_LABELS = [("document", "Document"),
                  ("definitions", "MetaDataVersion definitions"),
                  ("nested", "Nested elements"),
                  ("admin", "Administrative data")]
# the study header labels are padded to this width so their values line up
LABEL_WIDTH = 18
# a study or metadata description longer than this is truncated in the text report only
MAX_TEXT_WIDTH = 88
ABSENT = "-"


def model_label(model_package: str) -> str:
    return MODEL_LABELS.get(model_package, model_package)


def human_size(size_bytes: int) -> str:
    """
    the file size as bytes plus a rounded binary unit, e.g. "174,322 bytes (170.2 KiB)". Bytes are always
    shown because they are what a reader compares between two files
    """
    size, unit = float(size_bytes), None
    for candidate in ("KiB", "MiB", "GiB"):
        if size < 1024:
            break
        size, unit = size / 1024, candidate
    if unit is None:
        return f"{size_bytes:,} bytes"
    return f"{size_bytes:,} bytes ({size:.1f} {unit})"


def truncate(text: str, width: int = MAX_TEXT_WIDTH) -> str:
    """shortens a long free-text value for the text report; the JSON report keeps it whole"""
    return text if len(text) <= width else text[:width - 1].rstrip() + "…"


def standard_text(standard) -> str:
    """one Standard rendered as 'CDASHIG 2.2 IG (Final)', omitting what is not set"""
    parts = [p for p in (standard.name, standard.publishing_set, standard.version, standard.type) if p]
    text = " ".join(parts) or standard.oid
    return f"{text} ({standard.status})" if standard.status else text


def percent(value) -> str:
    return ABSENT if value is None else f"{value:.0f}%"


def render_text(result, show_forms: bool = True) -> str:
    """
    builds the formatted text report: header, notes, study, CRF, annotations, forms, element counts and
    summary
    :param result: the MetricsResult to render
    :param show_forms: when False, the per-form table is omitted
    :return: string
    """
    lines = _render_header(result)
    lines += [""] + _render_study(result)
    lines += [""] + _render_crf(result)
    lines += [""] + _render_annotations(result)
    if show_forms:
        lines += [""] + _render_forms(result)
    lines += [""] + _render_elements(result)
    lines += [""] + _render_summary(result)
    return "\n".join(lines)


def render_json(result, indent: int = 2) -> str:
    """
    builds the JSON report; unlike the text report it always includes the forms and never truncates a
    description
    :param result: the MetricsResult to render
    :param indent: JSON indent
    :return: string
    """
    report = {
        "crf_file": result.crf_file,
        "model_package": result.model_package,
        "odmlib_version": result.odmlib_version,
        "permissive": result.permissive,
        "file": {
            "size_bytes": result.size_bytes,
            "modified": result.file_modified,
        },
        "document": {
            "file_oid": result.file_oid,
            "file_type": result.file_type,
            "granularity": result.granularity,
            "creation_datetime": result.creation_datetime,
            "originator": result.originator,
            "source_system": result.source_system,
            "source_system_version": result.source_system_version,
            "odm_version": result.odm_version,
        },
        "study": {
            "oid": result.study_oid,
            "study_name": result.study_name,
            "protocol_name": result.protocol_name,
            "study_description": result.study_description,
            "metadata_version": {
                "oid": result.mdv_oid,
                "name": result.mdv_name,
                "description": result.mdv_description,
                "count": result.mdv_count,
            },
        },
        "standards": [asdict(s) for s in result.standards],
        "element_counts": [asdict(e) for e in result.elements],
        "crf": asdict(result.crf),
        "annotations": asdict(result.annotations),
        "visits": asdict(result.visits),
        "forms": [asdict(f) for f in result.forms],
        "totals": {
            "elements": result.total_elements,
            "element_types": result.element_types,
            "element_types_present": result.element_types_present,
            "element_types_absent": result.element_types_absent,
        },
        "notes": list(result.notes),
    }
    return json.dumps(report, indent=indent)


def _render_header(result) -> list:
    """renders the file identity block, the notes and, on a permissive run, the non-conformance banner"""
    model = model_label(result.model_package)
    lines = ["ODM v2.0 CRF metrics",
             f"  File:     {result.crf_file}",
             f"  Size:     {human_size(result.size_bytes)}"]
    if result.creation_datetime:
        lines.append(f"  Created:  {result.creation_datetime}  (ODM/@CreationDateTime)")
    lines += [f"  Modified: {result.file_modified}  (file system)",
              f"  Model:    {model} (odmlib {result.model_package}, odmlib {result.odmlib_version})"]
    for note in result.notes:
        lines += ["", f"NOTE: {note}"]
    if result.permissive:
        lines += ["",
                  f"NOTE: loaded in permissive mode - this file is not conformant {model}.",
                  "      Counts may be incomplete; run crfvalidate."]
    return lines


def _render_study(result) -> list:
    """renders the study identity block; absent values are omitted rather than shown empty"""
    lines = ["STUDY"]
    for label, value in (("Study name", result.study_name),
                         ("Protocol name", result.protocol_name),
                         ("Description", result.study_description)):
        if value:
            lines.append(_labelled(label, truncate(value)))
    if result.study_oid:
        lines.append(_labelled("Study OID", result.study_oid))
    if result.mdv_oid or result.mdv_name:
        versions = f"  (1 of {result.mdv_count} versions)" if result.mdv_count > 1 else ""
        lines.append(_labelled("MetaDataVersion", (result.mdv_oid or "") + versions))
        if result.mdv_name:
            lines.append(" " * (LABEL_WIDTH + 3) + truncate(result.mdv_name))
        if result.mdv_description:
            lines.append(" " * (LABEL_WIDTH + 3) + truncate(result.mdv_description))
    for label, value in (("ODM version", result.odm_version),
                         ("File OID", result.file_oid),
                         ("File type", _file_type(result)),
                         ("Originator", result.originator),
                         ("Source system", _source_system(result))):
        if value:
            lines.append(_labelled(label, value))
    if result.standards:
        label = f"Standards ({len(result.standards)})"
        lines += _wrap_value(label, ", ".join(standard_text(s) for s in result.standards))
    return lines


def _file_type(result):
    if result.file_type and result.granularity:
        return f"{result.file_type} ({result.granularity})"
    return result.file_type or result.granularity


def _source_system(result):
    """the source system with its version appended, when the document names one"""
    if result.source_system and result.source_system_version:
        return f"{result.source_system} {result.source_system_version}"
    return result.source_system or result.source_system_version


def _labelled(label: str, value: str) -> str:
    return f"  {label + ':':{LABEL_WIDTH}} {value}"


def _wrap_value(label: str, value: str) -> list:
    """a labelled value wrapped onto continuation lines aligned under the first one"""
    indent = " " * (LABEL_WIDTH + 3)
    lines = wrap(_labelled(label, value), width=98, subsequent_indent=indent)
    return lines or [_labelled(label, value)]


def _render_crf(result) -> list:
    """renders the CRF structure counts"""
    crf, visits = result.crf, result.visits
    lines = ["CRF"]
    forms = f"{crf.forms:,}"
    if visits.links:
        forms += f" ({crf.scheduled_forms:,} scheduled, {crf.unscheduled_forms:,} unscheduled)"
    lines.append(_labelled("Forms", forms))
    lines.append(_labelled("Sections", f"{crf.sections:,}"))
    lines.append(_labelled("Concepts", f"{crf.concepts:,}"))
    if crf.other_groups:
        lines.append(_labelled("Other groups", f"{crf.other_groups:,}"))
    lines.append(_labelled("Item definitions", f"{crf.item_defs:,}"))
    lines.append(_labelled("Items on forms", f"{crf.item_rows:,} rows ({crf.distinct_items:,} distinct, "
                                             f"{crf.mandatory_rows:,} mandatory)"))
    if crf.items_by_datatype:
        lines += _wrap_value("Items by DataType", ", ".join(f"{dt} {n:,}" for dt, n in crf.items_by_datatype.items()))
    lines.append(_labelled("Code lists", f"{crf.codelists:,} ({crf.codelist_items:,} items)"))
    lines.append(_labelled("Conditions", f"{crf.condition_defs:,}"))
    lines.append(_labelled("Methods", f"{crf.method_defs:,}"))
    lines.append(_labelled("Workflows", f"{crf.workflow_defs:,}"))
    events = f"{visits.study_events:,} study event{_s(visits.study_events)}"
    if visits.study_event_groups:
        events += f" in {visits.study_event_groups:,} group{_s(visits.study_event_groups)}"
    lines.append(_labelled("Visits", events))
    if visits.links:
        lines.append(_labelled("Visit-form links", f"{visits.links:,} (matrix {visits.study_events:,} x {crf.forms:,}, "
                                                   f"{percent(100 * visits.fill)} filled)"))
        if visits.unscheduled_forms:
            lines += _wrap_value("Unscheduled forms", ", ".join(visits.unscheduled_forms))
        if visits.events_without_forms:
            lines += _wrap_value("Visits without forms", ", ".join(visits.events_without_forms))
    return lines


def _render_annotations(result) -> list:
    """renders the SDTM annotation metrics"""
    a = result.annotations
    lines = ["ANNOTATIONS",
             _labelled("Items annotated", f"{a.annotated_items:,} of {a.distinct_items:,} ({percent(a.annotated_pct)})"),
             _labelled("By level", f"form {a.form_annotations:,}, section {a.section_annotations:,}, "
                                   f"concept {a.concept_annotations:,}, item {a.item_annotations:,}, "
                                   f"codelist item {a.codelist_item_annotations:,}"),
             _labelled("Parsed", f"{a.parsed:,} parsed, {a.partial:,} partial, {a.unparsed:,} unparsed"),
             _labelled("NOT SUBMITTED", f"{a.not_submitted:,}")]
    if a.datasets:
        lines += _wrap_value("Datasets", ", ".join(a.datasets))
    if a.unresolved_datasets:
        lines.append(_labelled("Unresolved", f"{a.unresolved_datasets:,} target{_s(a.unresolved_datasets)} with no "
                                             f"dataset (no qualifier, known prefix or group domain)"))
    return lines


def _render_forms(result) -> list:
    """renders one row per form, in display order"""
    lines = [f"FORMS ({len(result.forms)})"]
    if not result.forms:
        return lines + ["  No ItemGroupDef with Type='Form' is defined."]
    rows = [(f.oid or "", f.name or "", ", ".join(f.domains) or ABSENT, f"{f.sections:,}", f"{f.concepts:,}",
             f"{f.items:,}", f"{f.annotated:,}", f"{f.not_submitted:,}", f"{f.visits:,}")
            for f in result.forms]
    headings = ("OID", "Name", "Domains", "Sections", "Concepts", "Items", "Annotated", "Not submitted", "Visits")
    numeric = {3, 4, 5, 6, 7, 8}
    widths = [max(len(headings[i]), max(len(row[i]) for row in rows)) for i in range(len(headings))]
    lines.append("  " + _row(headings, widths, numeric))
    for row in rows:
        lines.append("  " + _row(row, widths, numeric))
    return lines


def _row(values, widths, numeric) -> str:
    cells = [f"{value:>{width}}" if i in numeric else f"{value:{width}}"
             for i, (value, width) in enumerate(zip(values, widths))]
    return "  ".join(cells).rstrip()


def _render_elements(result) -> list:
    """renders the element counts grouped into sections, one row per element type the model can hold --
    an element absent from the document is reported as 0, never omitted"""
    lines = ["ELEMENT COUNTS"]
    if not result.elements:
        return lines + ["  (the model defines no elements)"]
    name_width = max(len(e.element) for e in result.elements)
    count_width = max(len(f"{e.count:,}") for e in result.elements)
    for section, heading in SECTION_LABELS:
        elements = [e for e in result.elements if e.section == section]
        if not elements:
            continue
        lines.append(f"  {heading}")
        for element in elements:
            lines.append(f"    {element.element:{name_width}}  {element.count:>{count_width},}")
    return lines


def _render_summary(result) -> list:
    """renders the closing tallies: the element totals and the headline counts"""
    crf, visits = result.crf, result.visits
    lines = ["SUMMARY",
             f"  {result.total_elements:,} elements across {result.element_types:,} element types "
             f"({result.element_types_present:,} present, {result.element_types_absent:,} absent)"]
    headline = [f"{crf.forms:,} form{_s(crf.forms)}",
                f"{crf.item_rows:,} item row{_s(crf.item_rows)}",
                f"{crf.item_defs:,} item definition{_s(crf.item_defs)}",
                f"{crf.codelists:,} code list{_s(crf.codelists)}",
                f"{crf.method_defs:,} method{_s(crf.method_defs)}",
                f"{visits.links:,} visit-form link{_s(visits.links)}"]
    lines += wrap("  " + ", ".join(headline), width=98, subsequent_indent="  ")
    return lines


def _s(count: int) -> str:
    return "" if count == 1 else "s"
