import argparse
import sys
from pathlib import Path

from crfutils import __version__, _common
from crfutils.validate import CrfSchemaValidator, CrfSchemaValidationError, CrfSchemaLoadError


def main():
    """
    schema validates the ODM v2.0 file, reporting every error, and returns the exit code: 0 when the
    file is valid, 1 when it is invalid, and 2 when the validation could not be run at all -- the
    schema would not load, the file could not be read or parsed, or the report could not be written
    :return: int exit code
    """
    args = set_cmd_line_args()
    try:
        schema = Path(args.schema) if args.schema else None
        validator = CrfSchemaValidator(Path(args.crf), schema)
        if args.out:
            validator.validate_to_file(Path(args.out), max_locations=args.max_locations, as_json=args.json)
        elif args.json:
            print(validator.validate_to_json())
        else:
            validator.validate_to_console(max_locations=args.max_locations)
        return 1 if validator.validate().has_errors else 0
    except CrfSchemaLoadError as e:
        # CrfSchemaLoadError subclasses CrfSchemaValidationError, so it must be caught first. stderr
        # keeps the message out of a redirected report
        print(e, file=sys.stderr)
        return 2
    except CrfSchemaValidationError as e:
        print(e, file=sys.stderr)
        return 1


def set_cmd_line_args():
    """
    get the ODM file to validate, the schema to validate it against, and the reporting options from the
    command-line
    :return: the argparse object with the command-line parameters
    """
    parser = argparse.ArgumentParser(prog="crfvalidate")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-c", "--crf", help="path and file name of the ODM v2.0 CRF file", required=True,
                        dest="crf")
    parser.add_argument("-s", "--schema", help="path and file name of the schema (.xsd) to validate "
                        "against; omit to use the bundled ODM v2.0 schema", required=False, dest="schema",
                        default=None)
    parser.add_argument("-o", "--out", help="path and file name of the report to create; omit to print to "
                        "the console", required=False, dest="out", default=None)
    parser.add_argument("--json", help="emit JSON instead of the text listing", required=False, dest="json",
                        action="store_true")
    parser.add_argument("-L", "--max-locations", help="max example locations shown per finding (0 shows all)",
                        required=False, dest="max_locations", type=int, default=5)
    return parser.parse_args()


def run():
    """the entry point for both the crfvalidate command and python -m: exits with main()'s code. The
    command calls run() directly, never this module's __main__ block, so Ctrl-C and a closed pager are
    handled in _common.run"""
    _common.run(main)


if __name__ == "__main__":
    run()
