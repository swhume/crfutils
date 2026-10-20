"""Schema validation of an ODM v2.0 file against the bundled XSD, reporting every error.

A port of defineutils' validate module: errors are grouped by (check, element, reason) into findings,
each with the OID-decorated path and source line of every occurrence.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

import xmlschema as XSD
from lxml import etree
from xmlschema.exceptions import XMLSchemaException
from xmlschema.validators.exceptions import (XMLSchemaChildrenValidationError,
                                             XMLSchemaDecodeError)

from .. import _common
from .._odm import ODM_NS, ODM_SCHEMA
from . import report

DEFAULT_SCHEMA = ODM_SCHEMA

UNEXPECTED_CHILD = "unexpected_child"
INCOMPLETE_CONTENT = "incomplete_content"
INVALID_VALUE = "invalid_value"
ATTRIBUTE_ERROR = "attribute_error"
SCHEMA_VALIDATION = "schema_validation"

ERROR = "error"


class CrfSchemaValidationError(Exception):
    pass


class CrfSchemaLoadError(CrfSchemaValidationError):
    """raised when the validation could not be run at all -- the schema could not be loaded, the ODM
    file could not be read or parsed, or the report could not be written -- as opposed to the file being
    invalid. A subclass of CrfSchemaValidationError so callers that catch the parent keep working; the
    CLI catches it first to return exit code 2 rather than 1."""
    pass


@dataclass(frozen=True)
class Location:
    path: str                   # OID-decorated, e.g. "MetaDataVersion[MDV.1]/ItemDef[IT.VS.SYSBP]"
    line: Union[int, None]      # source line of the offending element


@dataclass
class Finding:
    check: str                  # "unexpected_child" | "invalid_value" | "attribute_error" | ...
    severity: str               # always "error"; kept so the reports share a finding shape
    element: str                # element name holding the error, e.g. "ItemDef"
    reason: str                 # the reason text as xmlschema phrased it
    message: str                # self-contained sentence, used in the JSON report
    detail: str                 # short form for the text listing, whose heading names the element
    locations: list = field(default_factory=list)


@dataclass
class ValidationResult:
    crf_file: str
    schema_file: str
    xmlschema_version: str
    root_namespace: Union[str, None]    # the root element's namespace, for the mismatch note
    bundled_schema: bool                # True when the bundled ODM v2.0 schema was used
    error_count: int                    # raw errors, before identical ones are grouped
    findings: list

    @property
    def errors(self) -> list:
        return [f for f in self.findings if f.severity == ERROR]

    @property
    def has_errors(self) -> bool:
        return any(f.severity == ERROR for f in self.findings)

    @property
    def is_valid(self) -> bool:
        return not self.findings

    @property
    def namespace_note(self) -> Union[str, None]:
        """a note when the file is not in the ODM v2.0 namespace but was validated against the bundled
        ODM v2.0 schema, since every error then stems from that"""
        if self.bundled_schema and self.root_namespace != ODM_NS:
            return (f"the root element is in the namespace {self.root_namespace or '(none)'}, not "
                    f"{ODM_NS}; the bundled schema is ODM v2.0, so the errors may all stem from that")
        return None


class CrfSchemaValidator:
    def __init__(self, crf_file: Path, xsd_file: Path = None):
        self.crf_file = Path(crf_file)
        self.xsd_file = Path(xsd_file) if xsd_file is not None else DEFAULT_SCHEMA
        self._bundled = xsd_file is None
        self._result = None
        try:
            self.xsd = XSD.XMLSchema(self.xsd_file)
        except XMLSchemaException as e:
            # XMLSchemaException covers the missing/unreadable path, the not-well-formed file, and
            # the well-formed file that is not a schema
            raise CrfSchemaLoadError(f"Could not load the schema {self.xsd_file}:\n{e}") from e

    def validate(self) -> ValidationResult:
        """
        schema validates the ODM file and collects every error, grouping identical errors into one
        finding; the result is cached so the report methods and the CLI exit code do not re-parse the
        file
        :return: ValidationResult
        """
        if self._result is not None:
            return self._result
        tree = self._parse_crf()
        root = tree.getroot()
        single_study = len(root.findall(f"{{{ODM_NS}}}Study")) == 1
        errors = list(self.xsd.iter_errors(tree))
        self._result = ValidationResult(
            crf_file=str(self.crf_file),
            schema_file=str(self.xsd_file),
            xmlschema_version=getattr(XSD, "__version__", "unknown"),
            root_namespace=etree.QName(root).namespace,
            bundled_schema=self._bundled,
            error_count=len(errors),
            findings=self._group(errors, single_study),
        )
        return self._result

    def validate_to_string(self, max_locations: int = 5) -> str:
        """
        validates and returns the formatted text listing
        :param max_locations: max example locations shown per finding (0 shows all)
        :return: string
        """
        return report.render_text(self.validate(), max_locations)

    def validate_to_file(self, out_file: Path, max_locations: int = 5, as_json: bool = False) -> None:
        """
        validates and writes the listing (text or JSON) to out_file
        :param out_file: Path to the file to save the report
        :param max_locations: max example locations shown per finding (0 shows all)
        :param as_json: when True, writes the JSON report instead of the text listing
        """
        if as_json:
            listing = self.validate_to_json()
        else:
            listing = self.validate_to_string(max_locations=max_locations)
        _common.write_text(out_file, listing + "\n", CrfSchemaLoadError)

    def validate_to_console(self, max_locations: int = 5) -> None:
        """
        validates and prints the formatted text listing to stdout
        :param max_locations: max example locations shown per finding (0 shows all)
        """
        print(self.validate_to_string(max_locations=max_locations))

    def validate_to_json(self, indent: int = 2) -> str:
        """
        validates and returns the results as a JSON string; every location is included even when the
        text listing truncates them
        :param indent: JSON indent
        :return: string
        """
        return report.render_json(self.validate(), indent)

    def _parse_crf(self):
        """
        parses the ODM file with lxml so every error carries a source line number -- handing xmlschema
        the file path instead leaves sourceline unset. Comments are stripped because lxml keeps them as
        child nodes, which shifts the child positions xmlschema reports
        :return: lxml ElementTree
        """
        try:
            return etree.parse(str(self.crf_file), etree.XMLParser(remove_comments=True))
        except etree.XMLSyntaxError as e:
            raise CrfSchemaLoadError(f"ODM file is not well-formed XML: {self.crf_file}.\n{e}") from e
        except OSError as e:
            raise CrfSchemaLoadError(f"ODM file not found: {self.crf_file}.\n{e}") from e

    def _group(self, errors: list, single_study: bool) -> list:
        """
        groups errors that say the same thing about the same kind of element into one finding, keeping
        every occurrence as a location; the biggest problems are listed first
        :param errors: the XMLSchemaValidationError list from iter_errors
        :param single_study: True when the document has one Study, so paths can drop it
        :return: list of Finding
        """
        findings = {}
        for error in errors:
            check, element = self._classify(error), self._element_name(error)
            reason = str(error.reason)
            key = (check, element, reason)
            if key not in findings:
                detail, message = report.finding_text(element, reason)
                findings[key] = Finding(check=check, severity=ERROR, element=element, reason=reason,
                                        message=message, detail=detail)
            findings[key].locations.append(self._location(error, single_study))
        return sorted(findings.values(), key=lambda f: (-len(f.locations), f.check, f.element))

    @staticmethod
    def _classify(error) -> str:
        """
        names the kind of error from the structure of the exception -- its class, whether it carries
        an offending tag, and the kind of schema component that rejected it -- rather than by matching
        on the reason text, which xmlschema formats and is free to reword
        :param error: an XMLSchemaValidationError
        :return: string check id
        """
        if isinstance(error, XMLSchemaChildrenValidationError):
            return UNEXPECTED_CHILD if error.invalid_tag is not None else INCOMPLETE_CONTENT
        if isinstance(error, XMLSchemaDecodeError):
            return INVALID_VALUE
        validator = type(getattr(error, "validator", None)).__name__
        if validator == "XsdAttributeGroup":
            # covers both a missing required attribute and one that is not allowed; the reason line
            # says which, and telling them apart would mean matching on that text
            return ATTRIBUTE_ERROR
        if "Facet" in validator:
            return INVALID_VALUE
        return SCHEMA_VALIDATION

    @staticmethod
    def _element_name(error) -> str:
        element = getattr(error, "elem", None)
        return etree.QName(element).localname if element is not None else "(document)"

    @staticmethod
    def _location(error, single_study: bool) -> Location:
        """
        builds an OID-decorated path by walking the offending element's ancestors, so a location reads
        MetaDataVersion[MDV.1]/ItemDef[IT.VS.SYSBP] rather than the positional path xmlschema reports
        :param error: an XMLSchemaValidationError
        :return: Location
        """
        segments, node = [], getattr(error, "elem", None)
        while node is not None:
            oid = node.get("OID") or (node.get("ID") if etree.QName(node).localname == "Leaf" else None)
            name = etree.QName(node).localname
            segments.append(f"{name}[{oid}]" if oid else name)
            node = node.getparent()
        return Location(path=_common.display_path("/".join(reversed(segments)), single_study),
                        line=getattr(error, "sourceline", None))
