"""
Writing a report to a folder is reported as a folder on every platform. Windows raises PermissionError there rather
than IsADirectoryError, so these tests make _common's open() raise PermissionError as Windows does, which runs that
branch on macOS and Linux too. The tests writing to a real folder are in each module's own test file.
"""
import pytest

from conftest import SYNTHETIC
from crfutils import _common
from crfutils.crfhtml import CrfHtml, CrfHtmlWriteError
from crfutils.crfpp import CrfPrettyPrinter, CrfPrettyPrintError
from crfutils.crfrefs import CrfRefChecker, CrfRefCheckError
from crfutils.metrics import CrfMetrics, CrfMetricsError
from crfutils.validate import CrfSchemaLoadError, CrfSchemaValidator

# each writer: a function writing its output to a path, and the error it raises. Every one writes through
# _common.write_text / write_bytes, so one patched open() covers them all
WRITERS = [
    pytest.param(lambda path: CrfPrettyPrinter(SYNTHETIC).pretty_print_to_file(path), CrfPrettyPrintError, id="crfpp"),
    pytest.param(lambda path: CrfRefChecker(SYNTHETIC).check_to_file(path), CrfRefCheckError, id="crfrefs"),
    pytest.param(lambda path: CrfMetrics(SYNTHETIC).collect_to_file(path), CrfMetricsError, id="crfmetrics"),
    pytest.param(lambda path: CrfSchemaValidator(SYNTHETIC).validate_to_file(path), CrfSchemaLoadError, id="crfvalidate"),
]


def _windows_open(file, *args, **kwargs):
    """open() as it fails on Windows for a folder, and for a file the user may not write"""
    raise PermissionError(13, "Permission denied", str(file))


@pytest.mark.parametrize("write, error", WRITERS)
def test_folder_is_reported_when_open_raises_permission_error(write, error, tmp_path, monkeypatch):
    monkeypatch.setattr(_common, "open", _windows_open, raising=False)

    with pytest.raises(error, match="write to a directory"):
        write(tmp_path)


@pytest.mark.parametrize("write, error", WRITERS)
def test_file_permission_error_is_reported_as_one(write, error, tmp_path, monkeypatch):
    monkeypatch.setattr(_common, "open", _windows_open, raising=False)

    with pytest.raises(error, match="Permission error attempting to write to"):
        write(tmp_path / "report.txt")


def test_crfhtml_checks_the_destination_before_transforming(tmp_path, monkeypatch):
    # crfhtml refuses a folder before the transform; a permission error on the file itself is reported as one
    monkeypatch.setattr(_common, "open", _windows_open, raising=False)

    with pytest.raises(CrfHtmlWriteError, match="write to a directory"):
        CrfHtml(SYNTHETIC).transform_to_html_file(tmp_path)
    with pytest.raises(CrfHtmlWriteError, match="Permission error attempting to write to"):
        CrfHtml(SYNTHETIC).transform_to_html_file(tmp_path / "crf.html")
