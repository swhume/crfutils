"""Pretty-printing (re-indenting) of an ODM v2.0 file.

The reformat is byte-preserving apart from whitespace: comments, processing instructions, element and
attribute order, namespaces and the xhtml markup inside TranslatedText are all retained.
"""
import sys
from pathlib import Path
from typing import Union

from lxml import etree

from .. import _common


class CrfPrettyPrintError(Exception):
    pass


class CrfPrettyPrinter:
    def __init__(self, crf_file: Path) -> None:
        self.crf_file = Path(crf_file)
        _common.require_file(self.crf_file, CrfPrettyPrintError)

    def pretty_print_to_string(self) -> str:
        """
        pretty-prints the ODM file and returns the formatted XML as a string
        :return: string
        """
        return self._pretty_print_bytes().decode("utf-8")

    def pretty_print_to_file(self, out_file: Path) -> None:
        """
        pretty-prints the ODM file and writes the formatted XML to out_file
        :param out_file: Path to the file to save the formatted output
        """
        _common.write_bytes(out_file, self._pretty_print_bytes(), CrfPrettyPrintError)

    def pretty_print_to_console(self, head: Union[int, None] = None) -> None:
        """
        pretty-prints the ODM file and writes the formatted XML to stdout, optionally limited to the
        first head lines so the output can be piped into a pager
        :param head: optional maximum number of lines to print to the console
        """
        lines = self.pretty_print_to_string().splitlines()
        if head is not None:
            lines = lines[:head]
        out = "\n".join(lines)
        if out:
            out += "\n"
        # BrokenPipeError (pager quits early) and KeyboardInterrupt (Ctrl-C) are handled by the CLI entry
        # point; the library method just writes so programmatic callers get normal exception semantics
        sys.stdout.write(out)
        sys.stdout.flush()

    def _pretty_print_bytes(self) -> bytes:
        """
        parses the ODM file and returns a pretty-printed (indented) UTF-8 XML byte string. Whitespace-only
        text nodes are dropped before re-indenting; text with content, including inside xhtml markup,
        is kept as it is
        :return: bytes
        """
        try:
            tree = etree.parse(str(self.crf_file), etree.XMLParser(remove_blank_text=True))
        except etree.XMLSyntaxError as e:
            raise CrfPrettyPrintError(f"Unable to parse {self.crf_file} as XML.\n{e}") from e
        except OSError as e:
            raise CrfPrettyPrintError(f"Unable to read {self.crf_file}.\n{e}") from e
        return etree.tostring(tree, pretty_print=True, xml_declaration=True, encoding="UTF-8")
