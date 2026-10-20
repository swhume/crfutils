import argparse
import sys
import traceback
from pathlib import Path

from crfutils import __version__, _common
from crfutils.metrics import CrfMetrics, CrfMetricsError


def main():
    """
    collects the CRF metrics and returns the exit code: 0 when the report was produced; 2 when it could
    not be -- the file is missing, would not load, or the report could not be written; and 1 when an
    unexpected error occurred, with its traceback on stderr. 1 is never a judgement on the file: a
    metrics report describes a file rather than judging it
    :return: int exit code
    """
    args = set_cmd_line_args()
    try:
        metrics = CrfMetrics(Path(args.crf), permissive=args.permissive)
        if args.out:
            metrics.collect_to_file(Path(args.out), show_forms=not args.no_forms, as_json=args.json)
        elif args.json:
            print(metrics.collect_to_json())
        else:
            metrics.collect_to_console(show_forms=not args.no_forms)
        return 0
    except CrfMetricsError as e:
        # the load failure message carries the crfvalidate guidance; stderr keeps it out of a redirected
        # report
        print(e, file=sys.stderr)
        return 2
    except BrokenPipeError:
        # quitting a pager is not a crash; _common.run exits 0 for it
        raise
    except Exception:
        traceback.print_exc()
        return 1


def set_cmd_line_args():
    """
    get the command-line arguments needed to report metrics on the CRF
    :return: the argparse object with the command-line parameters
    """
    parser = argparse.ArgumentParser(prog="crfmetrics")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-c", "--crf", help="path and file name of the ODM v2.0 CRF file to report on",
                        required=True, dest="crf")
    parser.add_argument("-o", "--out", help="path and file name of the report to create; omit to print to the "
                        "console", required=False, dest="out", default=None)
    parser.add_argument("--json", help="emit JSON instead of the text report", required=False, dest="json",
                        action="store_true")
    parser.add_argument("--no-forms", help="omit the per-form table from the text report", required=False,
                        dest="no_forms", action="store_true")
    parser.add_argument("--permissive", help="best-effort metrics for a non-conformant file", required=False,
                        dest="permissive", action="store_true")
    return parser.parse_args()


def run():
    """the entry point for both the crfmetrics command and python -m: exits with main()'s code. The command
    calls run() directly, never this module's __main__ block, so Ctrl-C and a closed pager are handled in
    _common.run"""
    _common.run(main)


if __name__ == "__main__":
    run()
