import argparse
import sys
import traceback
from pathlib import Path

from crfutils import __version__, _common
from crfutils.crfpdf import CrfPdf, CrfPdfError, report


def main():
    """
    renders the annotated CRF PDF and its page-references JSON and returns the exit code: 0 when both were
    written (warnings allowed); 2 when they were not -- the file is missing, is not ODM v2.0, has no forms,
    WeasyPrint is not available, or an output could not be written; and 1 when an unexpected error occurred,
    with its traceback on stderr
    :return: int exit code
    """
    args = set_cmd_line_args()
    try:
        pdf = CrfPdf(Path(args.crf), page_size=args.page_size, title=args.title,
                     visit_bookmarks=not args.no_visit_bookmarks, validate=args.validate,
                     codelist_items=args.codelist_items)
        written = pdf.write(pdf_file=Path(args.out) if args.out else None,
                            refs_file=Path(args.refs) if args.refs else None,
                            html_file=Path(args.html) if args.html else None)
        report(pdf.render(), written)
        return 0
    except CrfPdfError as e:
        print(e, file=sys.stderr)
        return 2
    except Exception:
        traceback.print_exc()
        return 1


def set_cmd_line_args():
    """
    get the command-line arguments needed to render the annotated CRF PDF
    :return: the argparse object with the command-line parameters
    """
    parser = argparse.ArgumentParser(prog="crfpdf")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-c", "--crf", help="path and file name of the ODM v2.0 CRF file", required=True, dest="crf")
    parser.add_argument("-o", "--out", help="path and file name of the PDF to create; omit to write "
                        "<crf name>_acrf.pdf beside the CRF", required=False, dest="out", default=None)
    parser.add_argument("--refs", help="path and file name of the page-references JSON to create; omit to write "
                        "<pdf name>.pagerefs.json beside the PDF", required=False, dest="refs", default=None,
                        metavar="PATH")
    parser.add_argument("--html", help="also save the intermediate HTML to this file", required=False, dest="html",
                        default=None, metavar="PATH")
    parser.add_argument("--page-size", help="letter (default) or a4", required=False, dest="page_size",
                        choices=["letter", "a4"], default="letter")
    parser.add_argument("--title", help="the document title; default 'Annotated CRF - <StudyName>'", required=False,
                        dest="title", default=None, metavar="TEXT")
    parser.add_argument("--no-visit-bookmarks", help="omit the Visits bookmark tree", dest="no_visit_bookmarks",
                        action="store_true")
    parser.add_argument("--codelist-items", help="list every option of a codelist with at most N items; a longer "
                        "codelist becomes a text field that names it (default 20)", required=False,
                        dest="codelist_items", type=int, default=20, metavar="N")
    parser.add_argument("--validate", help="schema validate the CRF first and refuse an invalid file", dest="validate",
                        action="store_true")
    return parser.parse_args()


def run():
    """the entry point for both the crfpdf command and python -m: exits with main()'s code. The command calls
    run() directly, never this module's __main__ block, so Ctrl-C is handled in _common.run"""
    _common.run(main)


if __name__ == "__main__":
    run()
