"""The page-references JSON crfpdf writes beside the PDF.

The JSON is a public contract: a Define-XML tool reads it to write the def:Origin of each SDTM variable and
value-level item -- the proposed Type and Source, and the def:PDFPageRef page references. Its shape and the key
grammar (annotations.target_key) are versioned by SCHEMA_VERSION; bump it on any change to either. This module
imports nothing from crfpdf.py -- it is handed plain values and duck-typed objects -- so it can be read on its own.
"""
from dataclasses import asdict
from typing import Iterable

from .. import annotations as A

SCHEMA_VERSION = "2.0"
KEY_FORMAT = "DATASET.VARIABLE[ where VAR = VALUE[ and ...]]"


def _target_dict(target) -> dict:
    return {
        "dataset": target.dataset,
        "dataset_source": target.dataset_source,
        "variable": target.variable,
        "variable_source": target.variable_source,
        "value": target.value,
        "where": [{"variable": c.variable, "comparator": c.comparator, "values": list(c.values), "source": c.source}
                  for c in target.where],
        "qnam": target.qnam,
        "key": target.key,
    }


def _keys(target) -> list:
    """the index keys a target is filed under: its key, its key without the concept conditions, and the
    variable-level roll-up of a value-level key"""
    keys = [target.key, A.annotation_key(target)]
    if target.dataset and target.where:
        keys.append(f"{target.dataset}.{target.variable}")
    return list(dict.fromkeys(keys))


def _instruction_dict(instruction) -> dict:
    return {"kind": instruction.kind, "variables": list(instruction.variables), "text": instruction.text}


def build(crf_file: str, pdf_file: str, pdf_sha256: str, page_count: int, page_size: str, design,
          forms: Iterable, annotations: Iterable, warnings: Iterable, generator: dict, generated: str) -> dict:
    """
    builds the page-references document
    :param design: the StudyDesign
    :param forms: FormPages per form in document order (oid, name, domains, named_destination, first_page,
        last_page, visits)
    :param annotations: AnnotationPages per rendered annotation (record, parsed, id, page, instruction,
        item_ref, origin)
    :param warnings: Warning records (check, text, form_oid, item_oid)
    :param generator: {"name", "version", "weasyprint"}
    :return: dict, ready for json.dumps
    """
    data = design.data
    merged, index, origins, domains = {}, {}, {}, {}
    for form in forms:
        for domain in form.domains:
            domains.setdefault(domain, set()).update(range(form.first_page, form.last_page + 1))
    for anno in annotations:
        record, parsed, item_ref, origin = anno.record, anno.parsed, anno.item_ref, anno.origin
        pages = {anno.page} if anno.page is not None else set()
        key = (record.level, record.form_oid, record.item_oid, record.coded_value, record.text)
        entry = merged.get(key)
        if entry is None:
            entry = merged[key] = {
                "level": record.level,
                "source": record.source,
                "form_oid": record.form_oid,
                "group_path": list(record.group_path),
                "item_oid": record.item_oid,
                "item_name": data.items[record.item_oid].name if record.item_oid in data.items else None,
                "codelist_oid": record.codelist_oid,
                "coded_value": record.coded_value,
                "text": record.text,
                "status": parsed.status,
                "not_submitted": parsed.not_submitted,
                "domains": list(parsed.domains),
                "targets": [],
                "item_origins": [{"type": o.type, "source": o.source} for o in item_ref.origins] if item_ref else [],
                "prespecified_value": item_ref.prespecified_value if item_ref else None,
                "mapping_instructions": _instruction_dict(anno.instruction) if anno.instruction else None,
                "proposed_origin": asdict(origin) if origin else None,
                "_target_keys": set(),
                "pages": set(),
                "occurrences": 0,
            }
        entry["pages"] |= pages
        entry["occurrences"] += 1
        for target in parsed.targets:
            if target.key not in entry["_target_keys"]:
                entry["_target_keys"].add(target.key)
                entry["targets"].append(_target_dict(target))
            if target.dataset:
                domains.setdefault(target.dataset, set()).update(pages)
            value = target.value if target.value is not None else (item_ref.prespecified_value if item_ref else None)
            for target_key in _keys(target):
                index.setdefault(target_key, set()).update(pages)
                if origin is None:
                    continue
                by_kind = origins.setdefault(target_key, {})
                proposed = by_kind.get((origin.type, origin.source))
                if proposed is None:
                    proposed = by_kind[(origin.type, origin.source)] = {
                        "type": origin.type, "source": origin.source, "description": origin.description,
                        "basis": [], "mapping": [], "values": [], "items": [], "pages": set()}
                for field_name, item in (("basis", origin.basis), ("values", value), ("items", record.item_oid),
                                         ("mapping", anno.instruction.kind if anno.instruction else None)):
                    if item is not None and item not in proposed[field_name]:
                        proposed[field_name].append(item)
                proposed["pages"] |= pages
    entries = []
    for entry in merged.values():
        entry.pop("_target_keys")
        entry["pages"] = sorted(entry["pages"])
        entries.append(entry)
    leaf = data.acrf_leaf
    return {
        "schema_version": SCHEMA_VERSION,
        "key_format": KEY_FORMAT,
        "generator": dict(generator),
        "generated": generated,
        "crf_file": crf_file,
        "pdf_file": pdf_file,
        "pdf_sha256": pdf_sha256,
        "page_count": page_count,
        "page_size": page_size,
        "study": {"oid": data.study_oid, "name": data.study_name, "protocol": data.protocol_name,
                  "mdv_oid": data.mdv_oid},
        "leaf": {"id": leaf.id, "href": leaf.href, "title": leaf.title} if leaf else None,
        "forms": [{"oid": f.oid, "name": f.name, "domains": list(f.domains), "named_destination": f.named_destination,
                   "first_page": f.first_page, "last_page": f.last_page, "visits": list(f.visits)} for f in forms],
        "visits": [{"oid": visit, "name": data.events[visit].name,
                    "forms": [ref.oid for ref in design.schedule.get(visit, [])]} for visit in design.visits],
        "annotations": entries,
        "index": {key: sorted(pages) for key, pages in sorted(index.items())},
        "origins": {key: [dict(proposed, pages=sorted(proposed["pages"])) for proposed in by_kind.values()]
                    for key, by_kind in sorted(origins.items())},
        "domains": {domain: sorted(pages) for domain, pages in sorted(domains.items())},
        "warnings": [asdict(w) for w in warnings],
    }
