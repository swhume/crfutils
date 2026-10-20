"""
With CRFUTILS_BIN naming a folder of commands -- the installed console scripts, or a frozen build -- each command
must behave as python -m does on the test files: the same exit code, stdout and stderr, and byte-identical HTML.
Skipped when CRFUTILS_BIN is not set, since python -m would then be compared with itself.
"""
import json
import os
import re
from pathlib import Path

import pytest

from conftest import fixture_path

pytestmark = pytest.mark.skipif(not os.environ.get("CRFUTILS_BIN"),
                                reason="compares the CRFUTILS_BIN commands with python -m")

CRFS = ["Result_ODMv2.xml", "crf_synthetic.xml"]

# each report command, with the options that change what it prints
REPORTS = [("crfvalidate",), ("crfvalidate", "--json"), ("crfpp",), ("crfrefs",), ("crfrefs", "--json"),
           ("crfmetrics",), ("crfmetrics", "--json")]

# the tail of the schema path crfvalidate loads by default, wherever its install or bundle is
DEFAULT_SCHEMA = ("crfutils", "validate", "schema", "odm-2-0", "ODM.xsd")

SCHEMA_LINE = re.compile(rb"^  Schema: (.*?)\r?$", re.MULTILINE)


def _without_schema(stdout: bytes, as_json: bool) -> tuple:
    """a validate report without the schema path, which names each install's own copy, and that path"""
    if as_json:
        report = json.loads(stdout)
        return report, report.pop("schema_file")
    return SCHEMA_LINE.sub(b"", stdout), SCHEMA_LINE.search(stdout).group(1).decode()


@pytest.mark.parametrize("crf", CRFS)
def test_crfhtml_writes_the_same_html(crf, tmp_path, run_cli, run_module):
    command = run_cli("crfhtml", "-c", str(fixture_path(crf)), "-o", str(tmp_path / "command.html"))
    module = run_module("crfhtml", "-c", str(fixture_path(crf)), "-o", str(tmp_path / "module.html"))

    assert command.returncode == module.returncode == 0
    assert (command.stdout, command.stderr) == (module.stdout, module.stderr)
    assert (tmp_path / "command.html").read_bytes() == (tmp_path / "module.html").read_bytes()


@pytest.mark.parametrize("crf", CRFS)
def test_crfreview_writes_the_same_html(crf, tmp_path, run_cli, run_module):
    # exit codes and files only: the windowed Windows build may have no stdout or stderr
    command = run_cli("crfreview", "--no-open", "-o", str(tmp_path / "command.html"), str(fixture_path(crf)))
    module = run_module("crfreview", "--no-open", "-o", str(tmp_path / "module.html"), str(fixture_path(crf)))

    assert command.returncode == module.returncode == 0
    assert (tmp_path / "command.html").read_bytes() == (tmp_path / "module.html").read_bytes()


@pytest.mark.parametrize("crf", CRFS)
@pytest.mark.parametrize("report", REPORTS, ids=" ".join)
def test_reports_match(crf, report, run_cli, run_module):
    name, *options = report
    args = ["-c", str(fixture_path(crf)), *options]

    command = run_cli(name, *args)
    module = run_module(name, *args)

    assert command.returncode == module.returncode
    assert command.stderr == module.stderr
    if name != "crfvalidate":
        assert command.stdout == module.stdout
        return
    command_report, schema = _without_schema(command.stdout, "--json" in options)
    module_report, _ = _without_schema(module.stdout, "--json" in options)
    assert command_report == module_report
    # the command found the bundled schema in its own install or bundle
    assert Path(schema).parts[-len(DEFAULT_SCHEMA):] == DEFAULT_SCHEMA
    assert Path(schema).is_file()
