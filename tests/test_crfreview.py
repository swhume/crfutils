"""
crfreview: renders a CRF, writes the HTML beside it (or to the temp folder) and opens it in the browser. The
in-process tests record what would be opened rather than starting a browser; the CLI tests always pass --no-open,
and check exit codes and files only, since the windowed Windows build may have no stdout or stderr.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from conftest import SYNTHETIC
from crfutils import __version__
from crfutils.crfhtml import CrfHtml
from crfutils import _common
from crfutils.crfreview import CrfViewer, CrfViewError, open_in_browser
from crfutils.crfreview import __main__ as crfreview_cli
from crfutils.crfreview import crfreview as crfreview_module


@pytest.fixture
def crf_copy(tmp_path: Path) -> Path:
    """a copy of the synthetic CRF, alone in its folder"""
    (tmp_path / "study").mkdir()
    crf = tmp_path / "study" / "study.xml"
    shutil.copy(SYNTHETIC, crf)
    return crf


@pytest.fixture
def temp(tmp_path: Path, monkeypatch) -> Path:
    """the temp folder crfreview writes to, in place of the real one"""
    folder = tmp_path / "temp"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    return folder


@pytest.fixture
def opened(monkeypatch) -> list:
    """the pages crfreview opens, recorded instead of opened"""
    pages = []
    monkeypatch.setattr(crfreview_cli, "open_in_browser", pages.append)
    return pages


def _main(monkeypatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["crfreview", *args])
    return crfreview_cli.main()


def _reference_html(crf: Path, tmp_path: Path) -> bytes:
    """the HTML crfhtml writes for the CRF"""
    out_file = tmp_path / "reference.html"
    CrfHtml(crf).transform_to_html_file(out_file)
    return out_file.read_bytes()


def _only_file(folder: Path) -> Path:
    files = [path for path in folder.rglob("*") if path.is_file()]
    assert len(files) == 1, files
    return files[0]


# where the HTML goes

def test_opens_the_html_written_beside_the_crf(crf_copy, temp, opened, tmp_path, monkeypatch):
    assert _main(monkeypatch, str(crf_copy)) == 0

    html_file = crf_copy.with_suffix(".html")
    assert opened == [html_file]
    assert html_file.read_bytes() == _reference_html(crf_copy, tmp_path)
    assert not list(temp.iterdir())


def test_replaces_an_html_file_beside_the_crf(crf_copy, temp, opened, monkeypatch):
    crf_copy.with_suffix(".html").write_text("an older page", encoding="utf-8")

    assert _main(monkeypatch, str(crf_copy)) == 0

    assert "</html>" in crf_copy.with_suffix(".html").read_text(encoding="utf-8")


def test_temp_writes_to_the_temp_folder(crf_copy, temp, opened, tmp_path, monkeypatch):
    assert _main(monkeypatch, "--temp", str(crf_copy)) == 0

    html_file = _only_file(temp)
    assert opened == [html_file]
    assert html_file == CrfViewer(crf_copy).temp_folder / "study.html"
    assert html_file.read_bytes() == _reference_html(crf_copy, tmp_path)
    assert not crf_copy.with_suffix(".html").exists()


def test_falls_back_to_temp_when_the_crf_folder_cant_be_written(crf_copy, temp, opened, tmp_path, monkeypatch):
    real_open = open

    def no_writing_beside_the_crf(file, *args, **kwargs):
        if Path(file).parent == crf_copy.parent:
            raise PermissionError(13, "Permission denied", str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(_common, "open", no_writing_beside_the_crf, raising=False)

    assert _main(monkeypatch, str(crf_copy)) == 0

    html_file = _only_file(temp)
    assert opened == [html_file]
    assert html_file.read_bytes() == _reference_html(crf_copy, tmp_path)
    assert not crf_copy.with_suffix(".html").exists()


def test_out_file(crf_copy, temp, opened, tmp_path, monkeypatch):
    out_file = tmp_path / "view.html"

    assert _main(monkeypatch, "-o", str(out_file), str(crf_copy)) == 0

    assert opened == [out_file]
    assert out_file.read_bytes() == _reference_html(crf_copy, tmp_path)


def test_no_open(crf_copy, temp, opened, tmp_path, monkeypatch):
    out_file = crf_copy.parent / "view.html"

    assert _main(monkeypatch, "--no-open", "-o", str(out_file), str(crf_copy)) == 0

    assert opened == []
    assert out_file.read_bytes() == _reference_html(crf_copy, tmp_path)


def test_each_crf_has_its_own_temp_folder(crf_copy, temp):
    other = crf_copy.parent.parent / "other" / crf_copy.name

    folder = CrfViewer(crf_copy).temp_folder

    assert folder.parent == temp / "crfutils"
    assert folder == CrfViewer(crf_copy.parent / ".." / "study" / crf_copy.name).temp_folder
    assert folder != CrfViewer(other).temp_folder


def test_temp_and_an_out_file_cant_be_combined(crf_copy, tmp_path):
    with pytest.raises(CrfViewError, match="not both"):
        CrfViewer(crf_copy, temp=True, out_file=tmp_path / "view.html")


# a CRF that can't be shown opens a page saying why

def _not_well_formed(folder: Path) -> Path:
    path = folder / "broken.xml"
    path.write_text("<ODM><broken></ODM>", encoding="utf-8")
    return path


def _not_odm_v2(folder: Path) -> Path:
    path = folder / "odm13.xml"
    path.write_text('<ODM xmlns="http://www.cdisc.org/ns/odm/v1.3" FileOID="F" FileType="Snapshot" '
                    'CreationDateTime="2026-01-01T00:00:00" ODMVersion="1.3.2"/>', encoding="utf-8")
    return path


@pytest.mark.parametrize("make, reason", [(lambda folder: folder / "missing.xml", "not found"),
                                          (_not_well_formed, "not well-formed XML"),
                                          (_not_odm_v2, "not an ODM v2.0 document")],
                         ids=["missing", "not well-formed", "not ODM v2.0"])
def test_a_crf_that_cant_be_shown_opens_an_error_page(make, reason, tmp_path, temp, opened, monkeypatch, capsys):
    (tmp_path / "study").mkdir()
    crf = make(tmp_path / "study")

    assert _main(monkeypatch, str(crf)) == 2

    page = CrfViewer(crf).temp_folder / f"{crf.stem}.error.html"
    assert opened == [page]
    text = page.read_text(encoding="utf-8")
    assert f"{crf.name} could not be shown" in text
    assert reason in text
    assert reason in capsys.readouterr().err
    # nothing is written beside the CRF, and the plain-XML link is offered when there is a file to show
    assert sorted(path.name for path in crf.parent.iterdir()) == ([crf.name] if crf.exists() else [])
    assert (f'href="{crf.as_uri()}"' in text) == crf.exists()


def test_the_error_page_escapes_the_message(crf_copy, temp):
    page = CrfViewer(crf_copy).write_error_page("<script>alert(1)</script> & more")

    text = page.read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; more" in text
    assert "<script>" not in text


def test_an_unexpected_error_opens_a_page_with_the_traceback(crf_copy, temp, opened, monkeypatch, capsys):
    def crash(self):
        raise RuntimeError("simulated defect")

    monkeypatch.setattr(CrfViewer, "write_html", crash)

    assert _main(monkeypatch, str(crf_copy)) == 1

    text = opened[0].read_text(encoding="utf-8")
    assert "failed unexpectedly" in text
    assert "RuntimeError: simulated defect" in text
    assert crfreview_module.ISSUES in text
    assert "Traceback" in capsys.readouterr().err


def test_a_browser_that_wont_start_is_reported(crf_copy, temp, monkeypatch, capsys):
    def no_browser(page):
        raise CrfViewError(f"No browser could be started to show {page}.")

    monkeypatch.setattr(crfreview_cli, "open_in_browser", no_browser)

    assert _main(monkeypatch, str(crf_copy)) == 2

    assert "No browser could be started" in capsys.readouterr().err


def test_an_error_page_that_cant_be_written_is_reported(tmp_path, opened, monkeypatch, capsys):
    not_a_folder = tmp_path / "temp"
    not_a_folder.write_text("", encoding="utf-8")
    monkeypatch.setattr(tempfile, "tempdir", str(not_a_folder))

    assert _main(monkeypatch, str(tmp_path / "missing.xml")) == 2

    assert opened == []
    err = capsys.readouterr().err
    assert "not found" in err
    assert "Unable to write" in err


# without a console, as on Windows, messages go to a message box

@pytest.fixture
def message_boxes(monkeypatch) -> list:
    shown = []
    monkeypatch.setattr(crfreview_cli, "WINDOWS", True)
    monkeypatch.setattr(crfreview_cli, "_message_box", shown.append)
    return shown


def _without_a_console(monkeypatch) -> None:
    """no stdout or stderr, as for a windowed Windows build. Called in the test itself: pytest's output capturing
    sets both again once the fixtures are set up"""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)


@pytest.mark.parametrize("args, code, message", [(["--version"], 0, f"crfreview {__version__}"),
                                                 ([], 2, "usage: crfreview"),
                                                 (["--temp", "-o", "x.html", "x.xml"], 2, "not allowed with")],
                         ids=["version", "no crf", "usage error"])
def test_without_a_console_argparse_output_goes_to_a_message_box(message_boxes, monkeypatch, args, code, message):
    _without_a_console(monkeypatch)

    with pytest.raises(SystemExit) as excinfo:
        _main(monkeypatch, *args)

    assert excinfo.value.code == code
    assert len(message_boxes) == 1
    assert message in message_boxes[0]


def test_without_a_console_a_problem_with_no_page_goes_to_a_message_box(message_boxes, tmp_path, opened, monkeypatch):
    not_a_folder = tmp_path / "temp"
    not_a_folder.write_text("", encoding="utf-8")
    monkeypatch.setattr(tempfile, "tempdir", str(not_a_folder))
    _without_a_console(monkeypatch)

    assert _main(monkeypatch, str(tmp_path / "missing.xml")) == 2

    assert len(message_boxes) == 1
    assert "not found" in message_boxes[0]
    assert "Unable to write" in message_boxes[0]


def test_without_a_console_a_shown_page_needs_no_message_box(message_boxes, crf_copy, temp, opened, monkeypatch):
    _without_a_console(monkeypatch)

    assert _main(monkeypatch, str(crf_copy)) == 0

    assert message_boxes == []


def test_with_a_console_the_help_is_printed(monkeypatch, capsys):
    with pytest.raises(SystemExit) as excinfo:
        _main(monkeypatch)

    assert excinfo.value.code == 2
    assert capsys.readouterr().out.startswith("usage: crfreview ")


# opening the page

def test_open_in_browser_opens_the_page_as_a_file_url(tmp_path, monkeypatch):
    urls = []
    monkeypatch.setattr(crfreview_module.webbrowser, "open", lambda url: urls.append(url) or True)

    open_in_browser(tmp_path / "study.html")

    assert urls == [(tmp_path / "study.html").as_uri()]


def test_open_in_browser_reports_a_browser_that_wont_start(tmp_path, monkeypatch):
    monkeypatch.setattr(crfreview_module.webbrowser, "open", lambda url: False)

    with pytest.raises(CrfViewError, match="No browser could be started"):
        open_in_browser(tmp_path / "study.html")


# the command, run as python -m, installed, or frozen (CRFUTILS_BIN); never opening a browser

@pytest.fixture
def temp_env(tmp_path: Path) -> tuple:
    """an environment whose temp folder is a new folder in tmp_path, and that folder"""
    folder = tmp_path / "temp"
    folder.mkdir()
    return {**os.environ, "TMPDIR": str(folder), "TEMP": str(folder), "TMP": str(folder)}, folder


def test_cli_writes_the_html_beside_the_crf(crf_copy, tmp_path, temp_env, run_cli):
    env, folder = temp_env

    completed = run_cli("crfreview", "--no-open", str(crf_copy), env=env)

    assert completed.returncode == 0
    assert crf_copy.with_suffix(".html").read_bytes() == _reference_html(crf_copy, tmp_path)
    assert not list(folder.iterdir())


def test_cli_temp_writes_to_the_temp_folder(crf_copy, temp_env, run_cli):
    env, folder = temp_env

    completed = run_cli("crfreview", "--no-open", "--temp", str(crf_copy), env=env)

    assert completed.returncode == 0
    assert _only_file(folder).name == "study.html"
    assert not crf_copy.with_suffix(".html").exists()


def test_cli_writes_the_html_to_out(crf_copy, tmp_path, run_cli):
    out_file = tmp_path / "view.html"

    completed = run_cli("crfreview", "--no-open", "-o", str(out_file), str(crf_copy))

    assert completed.returncode == 0
    assert out_file.read_text(encoding="utf-8") == CrfHtml(crf_copy).transform_to_html_string()


def test_cli_missing_file_exits_2_with_an_error_page(tmp_path, temp_env, run_cli):
    env, folder = temp_env

    completed = run_cli("crfreview", "--no-open", str(tmp_path / "missing.xml"), env=env)

    assert completed.returncode == 2
    page = _only_file(folder)
    assert page.name == "missing.error.html"
    assert "not found" in page.read_text(encoding="utf-8")


def test_cli_temp_and_out_exit_2(crf_copy, tmp_path, run_cli):
    completed = run_cli("crfreview", "--no-open", "--temp", "-o", str(tmp_path / "view.html"), str(crf_copy))

    assert completed.returncode == 2
    assert not (tmp_path / "view.html").exists()
