"""The crfutils commands: their console- and GUI-script entry points, and the run() each one calls."""
import importlib
import re
import sys
from importlib import metadata
from pathlib import Path

import pytest

import crfutils._common as common
from crfutils import __version__

# each command, and the module holding the run() its script calls
ENTRY_MODULES = {"crfvalidate": "crfutils.validate.__main__",
                 "crfhtml": "crfutils.crfhtml.__main__",
                 "crfpp": "crfutils.crfpp.__main__",
                 "crfrefs": "crfutils.crfrefs.__main__",
                 "crfmetrics": "crfutils.metrics.__main__",
                 "crfreview": "crfutils.crfreview.__main__",
                 "crfpdf": "crfutils.crfpdf.__main__"}

# the commands installed as GUI scripts, which on Windows start without a console window
GUI_SCRIPTS = ["crfreview"]

# the commands that print a report to the console, so can meet a pager that quits early
PAGED = ["crfvalidate", "crfpp", "crfrefs", "crfmetrics"]


def _installed():
    try:
        return metadata.distribution("crfutils")
    except metadata.PackageNotFoundError:
        pytest.skip("crfutils is not installed")


def _cli(name: str, monkeypatch):
    """the command's module, with os._exit swapped for sys.exit so run() can be called in-process"""
    monkeypatch.setattr(common, "_quiet_exit", sys.exit)
    return importlib.import_module(ENTRY_MODULES[name])


def test_each_command_is_a_console_or_gui_script_that_calls_run():
    scripts = {ep.name: ep for ep in _installed().entry_points if ep.group in ("console_scripts", "gui_scripts")}

    assert {name: (ep.group, ep.value) for name, ep in scripts.items()} == \
           {name: ("gui_scripts" if name in GUI_SCRIPTS else "console_scripts", f"{module}:run")
            for name, module in ENTRY_MODULES.items()}, \
           "the installed metadata is stale; re-run pip install -e ."
    for name, ep in scripts.items():
        assert ep.load() is importlib.import_module(ENTRY_MODULES[name]).run


def test_the_installed_version_is_the_package_version():
    # --version prints crfutils.__version__, so it must match the version that was installed
    assert _installed().version == __version__, "the installed metadata is stale; re-run pip install -e ."


def test_pyproject_version_is_the_package_version():
    # a regex rather than tomllib, which Python 3.10 does not have
    pyproject = (Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE).group(1) == __version__


def test_readme_version_badge_is_the_package_version():
    # the README's version badge is static (the package is not on PyPI); it must be updated with the version
    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    badge = re.search(r"!\[Version ([^\]]+)\]\(https://img\.shields\.io/badge/version-([^-]+)-", readme)
    assert badge, "README.md has no version badge"
    assert badge.group(1) == badge.group(2) == __version__, "the README version badge is stale"


@pytest.mark.parametrize("name", ENTRY_MODULES)
def test_version_flag(name, run_cli):
    completed = run_cli(name, "--version")

    assert completed.returncode == 0
    assert completed.stdout.decode().strip() == f"{name} {__version__}"


@pytest.mark.parametrize("name", ENTRY_MODULES)
def test_help_names_the_command(name, run_cli):
    completed = run_cli(name, "--help")

    assert completed.returncode == 0
    assert completed.stdout.decode().startswith(f"usage: {name} ")


@pytest.mark.parametrize("name", ENTRY_MODULES)
def test_run_exits_with_the_code_main_returns(name, monkeypatch):
    module = _cli(name, monkeypatch)
    monkeypatch.setattr(module, "main", lambda: 2)

    with pytest.raises(SystemExit) as excinfo:
        module.run()
    assert excinfo.value.code == 2


@pytest.mark.parametrize("name", ENTRY_MODULES)
def test_run_exits_130_on_ctrl_c(name, monkeypatch):
    def interrupted():
        raise KeyboardInterrupt

    module = _cli(name, monkeypatch)
    monkeypatch.setattr(module, "main", interrupted)

    with pytest.raises(SystemExit) as excinfo:
        module.run()
    assert excinfo.value.code == 130


@pytest.mark.parametrize("name", PAGED)
def test_run_exits_0_when_the_pager_closes(name, monkeypatch):
    def closed_pipe():
        raise BrokenPipeError

    module = _cli(name, monkeypatch)
    monkeypatch.setattr(module, "main", closed_pipe)

    with pytest.raises(SystemExit) as excinfo:
        module.run()
    assert excinfo.value.code == 0
