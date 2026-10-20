import argparse
import contextlib
import io
import sys
import traceback
from pathlib import Path

from crfutils import __version__
from crfutils.crfhtml import CrfHtmlGenerationError
from crfutils.crfreview import CrfViewer, CrfViewError, open_in_browser

WINDOWS = sys.platform == "win32"


def main():
    """
    shows the CRF in the default browser and returns the exit code: 0 when the HTML was opened (or, with
    --no-open, written); 2 when it was not -- the CRF is missing, is not well-formed ODM v2.0, or the HTML could
    not be written -- and a page saying why was opened instead; and 1 when an unexpected error occurred, with
    its traceback on that page. Problems also go to stderr when there is one; on Windows crfreview has no
    console, so one with no page to show it is shown in a message box. Ctrl-C exits 130
    :return: int exit code
    """
    args = parse_args()
    viewer = CrfViewer(Path(args.crf), temp=args.temp, out_file=Path(args.out) if args.out else None)
    code, problem = 0, None
    try:
        page = viewer.write_html()
    except CrfHtmlGenerationError as e:
        code, problem = 2, str(e)
    except Exception:
        code, problem = 1, traceback.format_exc()
    if problem is not None and sys.stderr is not None:
        print(problem.rstrip(), file=sys.stderr)
    try:
        if problem is not None:
            page = viewer.write_error_page(problem, unexpected=code == 1)
        if not args.no_open:
            open_in_browser(page)
    except CrfViewError as e:
        # with no page to show it on, the problem goes in the message too, unless it is already on stderr
        tell_user(str(e) if problem is None or sys.stderr is not None else f"{problem.rstrip()}\n\n{e}")
        return code or 2
    return code


def parse_args() -> argparse.Namespace:
    """
    the command-line arguments. Without a console (crfreview on Windows), what argparse prints -- the help,
    --version, a usage error -- is shown with tell_user instead of being lost
    :return: the argparse object with the command-line parameters
    """
    if sys.stdout is not None and sys.stderr is not None:
        return set_cmd_line_args()
    printed = io.StringIO()
    try:
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
            return set_cmd_line_args()
    finally:
        if printed.getvalue():
            tell_user(printed.getvalue().rstrip())


def set_cmd_line_args():
    """
    get the command-line arguments needed to show a CRF in the browser; the CRF is positional, since that is how
    Windows passes the file opened with crfreview
    :return: the argparse object with the command-line parameters
    """
    parser = argparse.ArgumentParser(
        prog="crfreview",
        description="renders an ODM v2.0 CRF as HTML and opens it in the default browser. The HTML is written "
                    "beside the CRF as <crf name>.html, or to the temp folder when that folder can't be written "
                    "to. On Windows, choose crfreview once with a CRF's right-click > Open with, to open ODM "
                    "files with a double-click.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("crf", nargs="?", metavar="crf.xml", help="path and file name of the ODM v2.0 CRF file")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--temp", help="write the HTML to the temp folder rather than beside the CRF", dest="temp",
                       action="store_true")
    where.add_argument("-o", "--out", help="path and file name of the HTML file to write", dest="out", default=None)
    parser.add_argument("--no-open", help="write the HTML without opening it in the browser", dest="no_open",
                        action="store_true")
    args = parser.parse_args()
    if args.crf is None:
        # starting crfreview itself, rather than opening a CRF with it, shows how to use it
        parser.print_help()
        parser.exit(2)
    return args


def tell_user(message: str) -> None:
    """
    shows a message that has no page to go on: on stderr when there is one, otherwise on Windows in a message box,
    since crfreview is built without a console there
    """
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    elif WINDOWS:
        _message_box(message)


def _message_box(message: str) -> None:
    """an error message box, which waits until the user closes it"""
    import ctypes
    mb_iconerror = 0x10
    ctypes.windll.user32.MessageBoxW(None, message, "crfreview", mb_iconerror)


def run():
    """
    the entry point for both the crfreview command and python -m: exits with main()'s code. The command calls run()
    directly, never this module's __main__ block, so Ctrl-C is handled here
    """
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # 130 == 128 + SIGINT, the conventional Ctrl-C status
        sys.exit(130)


if __name__ == "__main__":
    run()
