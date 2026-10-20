"""
crfpdf without WeasyPrint: a missing package raises ImportError, and a missing Pango raises OSError from inside the
import; both become a CrfPdfError with install guidance (exit 2), and the other commands never import either.
"""
import sys

import pytest

from conftest import SYNTHETIC
from crfutils.crfpdf import CrfPdf, CrfPdfError, INSTALL_HELP
from crfutils.crfpdf import crfpdf as crfpdf_module
from crfutils.crfpdf import __main__ as crfpdf_cli


@pytest.mark.parametrize("error", [OSError("cannot load library 'libgobject-2.0-0'"),
                                   ImportError("No module named 'weasyprint'")], ids=["no Pango", "no WeasyPrint"])
def test_missing_engine_is_reported_with_guidance(error, monkeypatch):
    def failing_import():
        raise error

    monkeypatch.setattr(crfpdf_module, "_import_engines", failing_import)

    with pytest.raises(CrfPdfError) as excinfo:
        CrfPdf(SYNTHETIC).render()
    message = str(excinfo.value)
    assert str(error) in message
    assert 'pip install "crfutils[pdf]"' in message and "Pango" in message
    assert message.endswith(INSTALL_HELP)


def test_cli_exits_2_with_guidance(monkeypatch, capsys, tmp_path):
    def failing_import():
        raise OSError("cannot load library 'libpango-1.0-0'")

    monkeypatch.setattr(crfpdf_module, "_import_engines", failing_import)
    monkeypatch.setattr(sys, "argv", ["crfpdf", "-c", str(SYNTHETIC), "-o", str(tmp_path / "acrf.pdf")])

    assert crfpdf_cli.main() == 2

    err = capsys.readouterr().err
    assert "libpango-1.0-0" in err and 'pip install "crfutils[pdf]"' in err
    assert not list(tmp_path.iterdir())


def test_the_other_commands_do_not_import_weasyprint(run_cli):
    code = ("import sys; import crfutils.crfhtml, crfutils.validate, crfutils.crfpp, crfutils.crfrefs, "
            "crfutils.metrics, crfutils.crfreview; "
            "print(sorted(m for m in sys.modules if m.split('.')[0] in ('weasyprint', 'pypdf')))")
    import subprocess
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert completed.returncode == 0
    assert completed.stdout.strip() == "[]"
