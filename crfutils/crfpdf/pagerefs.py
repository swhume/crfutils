"""The page-references JSON crfpdf writes beside the PDF.

The JSON is a public contract: a Define-XML tool reads it to write def:PDFPageRef page references into the
def:Origin of each collected variable. Its shape and the key grammar (annotations.target_key) are versioned
by SCHEMA_VERSION; bump it on any change to either. This module imports nothing from crfpdf.py -- it is
handed plain values and duck-typed objects -- so it can be read on its own.
"""
from dataclasses import asdict
from typing import Iterable, Union

SCHEMA_VERSION = "1.0"
KEY_FORMAT = "DATASET.VARIABLE[ where VAR = VALUE[ and ...]]"


def _target_dict(target) -> dict:
    return {
        "dataset": target.dataset,
        "dataset_source": target.dataset_source,
        "variable": target.variable,
        "value": target.value,
        "where": [{"variable": c.variable, "comparator": c.comparator, "values": list(c.values)} for c in target.where],
        "qnam": target.qnam,
        "key": target.key,
    }


def _roll_up(key: str, target) -> Union[str, None]:
    """the variable-level key a value-level key rolls up into, or None when it is already variable-level"""
    if target.dataset and target.where:
        return f"{target.dataset}.{target.variable}"
    return None


def build(crf_file: str, pdf_file: str, pdf_sha256: str, page_count: int, page_size: str, design,
          forms: Iterable, annotations: Iterable, warnings: Iterable, generator: dict, generated: str) -> dict:
    """
    builds the page-references document
    :param design: the StudyDesign
    :param forms: FormPages per form in document order (oid, name, domains, named_destination, first_page,
        last_page, visits)
    :param annotations: AnnotationPages per rendered annotation (record, parsed, id, page)
    :param warnings: Warning records (check, text, form_oid, item_oid)
    :param generator: {"name", "version", "weasyprint"}
    :return: dict, ready for json.dumps
    """
    data = design.data
    merged = {}
    for anno in annotations:
        record, parsed = anno.record, anno.parsed
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
                "_target_keys": set(),
                "pages": set(),
                "occurrences": 0,
            }
        for target in parsed.targets:
            if target.key not in entry["_target_keys"]:
                entry["_target_keys"].add(target.key)
                entry["targets"].append(_target_dict(target))
        if anno.page is not None:
            entry["pages"].add(anno.page)
        entry["occurrences"] += 1
    index, domains = {}, {}
    for form in forms:
        for domain in form.domains:
            domains.setdefault(domain, set()).update(range(form.first_page, form.last_page + 1))
    entries = []
    for entry in merged.values():
        pages = sorted(entry.pop("pages"))
        entry.pop("_target_keys")
        entry["pages"] = pages
        for target in entry["targets"]:
            index.setdefault(target["key"], set()).update(pages)
            if target["dataset"] and target["where"]:
                index.setdefault(f"{target['dataset']}.{target['variable']}", set()).update(pages)
            if target["dataset"]:
                domains.setdefault(target["dataset"], set()).update(pages)
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
        "domains": {domain: sorted(pages) for domain, pages in sorted(domains.items())},
        "warnings": [asdict(w) for w in warnings],
    }
