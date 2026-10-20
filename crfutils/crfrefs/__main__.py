import argparse
import sys
from pathlib import Path

from crfutils import __version__, _common
from crfutils.crfrefs import CrfRefChecker, CrfRefCheckError


def main():
    """
    runs the OID reference/definition checks and returns the exit code: 0 when there are no errors (a
    clean file, or one with warnings only), 1 when there are errors, and 2 when the check could not be
    run -- the file would not load, or the report could not be written
    :return: int exit code
    """
    args = set_cmd_line_args()
    try:
        checker = CrfRefChecker(Path(args.crf), permissive=args.permissive)
        if args.out:
            checker.check_to_file(Path(args.out), errors_only=args.errors_only, max_locations=args.max_locations,
                                  as_json=args.json)
        elif args.json:
            print(checker.check_to_json(errors_only=args.errors_only))
        else:
            checker.check_to_console(errors_only=args.errors_only, max_locations=args.max_locations)
        return 1 if checker.check().has_errors else 0
    except CrfRefCheckError as e:
        # the load failure message carries the crfvalidate guidance; stderr keeps it out of a redirected
        # report
        print(e, file=sys.stderr)
        return 2


def set_cmd_line_args():
    """
    get the command-line arguments needed to check the CRF
    :return: the argparse object with the command-line parameters
    """
    parser = argparse.ArgumentParser(prog="crfrefs")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-c", "--crf", help="path and file name of the ODM v2.0 CRF file to check", required=True,
                        dest="crf")
    parser.add_argument("-o", "--out", help="path and file name of the report to create; omit to print to the "
                        "console", required=False, dest="out", default=None)
    parser.add_argument("--json", help="emit JSON instead of the text listing", required=False, dest="json",
                        action="store_true")
    parser.add_argument("--errors-only", help="suppress the warnings", required=False, dest="errors_only",
                        action="store_true")
    parser.add_argument("-L", "--max-locations", help="max example locations shown per finding (0 shows all)",
                        required=False, dest="max_locations", type=int, default=5)
    parser.add_argument("--permissive", help="best-effort check of a non-conformant file", required=False,
                        dest="permissive", action="store_true")
    return parser.parse_args()


def run():
    """the entry point for both the crfrefs command and python -m: exits with main()'s code. The command
    calls run() directly, never this module's __main__ block, so Ctrl-C and a closed pager are handled in
    _common.run"""
    _common.run(main)


if __name__ == "__main__":
    run()
