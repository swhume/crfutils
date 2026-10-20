"""Fixtures shared by the tests."""
import itertools
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from lxml import etree, html

DATA = Path(__file__).parent / "data"
ROOT = Path(__file__).parent.parent
SYNTHETIC = DATA / "crf_synthetic.xml"

# every ODM v2.0 test file; tests/data/README.md records where each came from
FIXTURES = ["vital_signs_odmv2-0.xml", "cdash_demo_v20.xml", "Result_ODMv2.xml", "Atlas_QS_ODMv2.xml",
            "Columbia-Suicide_Severity_Scale_ODMv2.xml", "Demographics_RACE_check_all_that_apply.xml",
            "crf_synthetic.xml"]

# each command, and the module python -m runs for it
COMMANDS = {"crfvalidate": "crfutils.validate",
            "crfhtml": "crfutils.crfhtml",
            "crfpp": "crfutils.crfpp",
            "crfrefs": "crfutils.crfrefs",
            "crfmetrics": "crfutils.metrics",
            "crfreview": "crfutils.crfreview",
            "crfpdf": "crfutils.crfpdf"}

# a command that waits on a message box, which no one can close in CI, fails rather than hanging the run
CLI_TIMEOUT = 180


def fixture_path(name: str) -> Path:
    return DATA / name


@pytest.fixture
def cli_command():
    """
    returns command(name): the argv that starts the named command. By default that is
    python -m <module>, which resolves from the repo root whether or not the package is installed.
    When the CRFUTILS_BIN environment variable names a folder of commands -- the installed console
    scripts, or a frozen build -- the command in that folder is run instead
    """
    def command(name: str) -> list:
        bin_dir = os.environ.get("CRFUTILS_BIN")
        if not bin_dir:
            return [sys.executable, "-m", COMMANDS[name]]
        found = shutil.which(name, path=bin_dir)
        if found is None:
            pytest.fail(f"{name} was not found in CRFUTILS_BIN={bin_dir}")
        return [found]

    return command


@pytest.fixture
def run_cli(cli_command):
    """
    returns run(name, *args, env=None): runs the named command from the repo root, capturing its output; env
    replaces the environment, e.g. to point the temp folder elsewhere
    """
    def run(name: str, *args: str, env: dict = None) -> subprocess.CompletedProcess:
        return subprocess.run([*cli_command(name), *args], capture_output=True, cwd=str(ROOT), env=env,
                              timeout=CLI_TIMEOUT)

    return run


@pytest.fixture
def run_module():
    """
    returns run(name, *args): runs the named command's module with python -m from the repo root, in UTF-8 mode
    as a frozen build would run. It is the reference the CRFUTILS_BIN commands are compared with, so it ignores
    CRFUTILS_BIN; every other CLI test uses run_cli
    """
    def run(name: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-X", "utf8", "-m", COMMANDS[name], *args], capture_output=True,
                              cwd=str(ROOT), timeout=CLI_TIMEOUT)

    return run


@pytest.fixture
def edited_crf(tmp_path):
    """
    returns make(edit, source): writes a copy of a test CRF to tmp_path after edit(tree) changes it with lxml,
    and returns its path. Broken or unusual files are built this way rather than committed
    """
    counter = itertools.count(1)

    def make(edit=None, source: Path = SYNTHETIC) -> Path:
        tree = etree.parse(str(source))
        if edit is not None:
            edit(tree)
        path = tmp_path / f"edited-{next(counter)}-{Path(source).name}"
        tree.write(str(path), xml_declaration=True, encoding="utf-8")
        return path

    return make


@pytest.fixture
def render():
    """returns render(path, **options): the CRF rendered by CrfHtml and parsed as HTML"""
    from crfutils.crfhtml import CrfHtml

    def render_html(path: Path, **options) -> html.HtmlElement:
        return html.fromstring(CrfHtml(path, **options).transform_to_html_string())

    return render_html


@pytest.fixture
def weasyprint_required():
    """skips the test when WeasyPrint, or the Pango it needs, is not installed; importorskip is not enough
    because a missing Pango raises OSError, not ImportError"""
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError) as e:
        pytest.skip(f"WeasyPrint is not available: {e}")
