import argparse
import errno
import sys
import traceback
from pathlib import Path

from crfutils import __version__, _common
from crfutils.crfpp import CrfPrettyPrinter, CrfPrettyPrintError


def main():
    """
    pretty-prints the ODM file and returns the exit code: 0 when it was written or printed, 2 when it
    was not (the file is missing or not well-formed XML, or the output could not be written), and 1 when
    an unexpected error occurred, with its traceback on stderr
    :return: int exit code
    """
    args = set_cmd_line_args()
    try:
        pp = CrfPrettyPrinter(Path(args.crf))
        if args.out:
            pp.pretty_print_to_file(Path(args.out))
        else:
            pp.pretty_print_to_console(head=args.head)
        return 0
    except CrfPrettyPrintError as e:
        print(e, file=sys.stderr)
        return 2
    except BrokenPipeError:
        # quitting a pager is not a crash; _common.run exits 0 for it
        raise
    except OSError as e:
        # Windows may surface a closed pipe as a bare OSError (e.g. [Errno 22]) rather than a
        # BrokenPipeError. A genuine -o output-file error is not a broken pipe
        if not args.out and e.errno in (errno.EINVAL, errno.EPIPE):
            _common._quiet_exit(0)
        traceback.print_exc()
        return 1
    except Exception:
        traceback.print_exc()
        return 1


def set_cmd_line_args():
    """
    get the command-line arguments needed to pretty-print the ODM file
    :return: the argparse object with the command-line parameters
    """
    parser = argparse.ArgumentParser(prog="crfpp")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-c", "--crf", help="path and file name of the ODM v2.0 CRF file to pretty-print",
                        required=True, dest="crf")
    parser.add_argument("-o", "--out", help="path and file name of the formatted file to create; omit to "
                        "print to the console", required=False, dest="out", default=None)
    parser.add_argument("-H", "--head", help="max number of lines to print to the console (ignored when -o "
                        "is set)", required=False, dest="head", type=int, default=None)
    return parser.parse_args()


def run():
    """the entry point for both the crfpp command and python -m. The command calls run() directly,
    never this module's __main__ block, so the Ctrl-C and broken-pipe handling in _common.run applies"""
    _common.run(main)


if __name__ == "__main__":
    run()
