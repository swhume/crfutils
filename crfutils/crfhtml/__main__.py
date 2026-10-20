import argparse
import sys
import traceback
from pathlib import Path

from crfutils import __version__, _common
from crfutils.crfhtml import CrfHtml, CrfHtmlGenerationError, print_notes


def main():
    """
    renders the CRF as HTML and returns the exit code: 0 when the HTML was written; 2 when it was not
    -- the file is missing, is not well-formed ODM v2.0, has no forms, the transform failed, or the HTML
    could not be written; and 1 when an unexpected error occurred, with its traceback on stderr
    :return: int exit code
    """
    args = set_cmd_line_args()
    # -o defaults to <crf stem>.html beside the input; CrfHtml refuses an -o that is the input
    out = Path(args.out) if args.out else Path(args.crf).with_suffix(".html")
    try:
        renderer = CrfHtml(Path(args.crf), annotations=not args.blank, types=args.types, toc=not args.no_toc,
                           visit_matrix=not args.no_visit_matrix)
        renderer.transform_to_html_file(out)
        print_notes(renderer.notes)
        return 0
    except CrfHtmlGenerationError as e:
        print(e, file=sys.stderr)
        return 2
    except Exception:
        traceback.print_exc()
        return 1


def set_cmd_line_args():
    """
    get the command-line arguments needed to render the CRF as HTML
    :return: the argparse object with the command-line parameters
    """
    parser = argparse.ArgumentParser(prog="crfhtml")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-c", "--crf", help="path and file name of the ODM v2.0 CRF file", required=True,
                        dest="crf")
    parser.add_argument("-o", "--out", help="path and file name of the HTML file to create; omit to write "
                        "<crf name>.html beside the CRF", required=False, dest="out", default=None)
    parser.add_argument("--blank", help="render a blank CRF, without the SDTM annotations", dest="blank",
                        action="store_true")
    parser.add_argument("--types", help="show each item's DataType and Length", dest="types",
                        action="store_true")
    parser.add_argument("--no-toc", help="omit the table of contents", dest="no_toc", action="store_true")
    parser.add_argument("--no-visit-matrix", help="omit the visit matrix", dest="no_visit_matrix",
                        action="store_true")
    return parser.parse_args()


def run():
    """the entry point for both the crfhtml command and python -m: exits with main()'s code. The command
    calls run() directly, never this module's __main__ block, so Ctrl-C is handled in _common.run"""
    _common.run(main)


if __name__ == "__main__":
    run()
