"""crfpp: pretty-printing, byte-preserving apart from whitespace."""
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from lxml import etree

from conftest import FIXTURES, ROOT, SYNTHETIC, fixture_path
from crfutils.crfpp import CrfPrettyPrinter, CrfPrettyPrintError

XHTML_NS = "http://www.w3.org/1999/xhtml"


@pytest.fixture
def big_crf(tmp_path) -> Path:
    """a CRF several megabytes long -- the synthetic file with its ItemDefs repeated -- so crfpp is still writing
    to the pipe, whatever the OS pipe buffer holds, when the reader goes away or Ctrl-C arrives"""
    tree = etree.parse(str(SYNTHETIC))
    mdv = tree.getroot().find(f"{{http://www.cdisc.org/ns/odm/v2.0}}Study/{{http://www.cdisc.org/ns/odm/v2.0}}MetaDataVersion")
    items = mdv.findall("{http://www.cdisc.org/ns/odm/v2.0}ItemDef")
    for n in range(400):
        for item in items:
            copy = etree.fromstring(etree.tostring(item))
            copy.set("OID", f"{item.get('OID')}.{n}")
            items[-1].addnext(copy)
    path = tmp_path / "big.xml"
    tree.write(str(path), xml_declaration=True, encoding="utf-8")
    assert path.stat().st_size > 2_000_000
    return path


def _run_pp_console(command: list, crf: Path) -> subprocess.Popen:
    """Launch crfpp on a file larger than the OS pipe buffer, with stdout/stderr piped, from the repo root"""
    return subprocess.Popen([*command, "-c", str(crf)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=str(ROOT))


def _c14n(data: bytes) -> bytes:
    """the canonical form of a document, with whitespace-only text removed, for comparing reformats"""
    tree = etree.fromstring(data, etree.XMLParser(remove_blank_text=True))
    return etree.tostring(tree, method="c14n")


def test_pretty_print_to_string_basic():
    xml = CrfPrettyPrinter(SYNTHETIC).pretty_print_to_string()

    assert isinstance(xml, str)
    assert xml.lstrip().startswith("<?xml")
    assert "<ODM" in xml and "</ODM>" in xml


def test_pretty_print_is_indented():
    lines = CrfPrettyPrinter(SYNTHETIC).pretty_print_to_string().splitlines()

    assert len(lines) > 100
    assert any(line.startswith("  <") for line in lines)


@pytest.mark.parametrize("name", FIXTURES)
def test_pretty_print_preserves_content(name):
    source = fixture_path(name)
    pretty = CrfPrettyPrinter(source).pretty_print_to_string().encode("utf-8")

    # canonically equal after whitespace-only text is removed: the same elements, attributes and text
    assert _c14n(pretty) == _c14n(source.read_bytes())
    # element and comment counts are unchanged
    src = etree.parse(str(source)).getroot()
    out = etree.fromstring(pretty)
    assert len(list(src.iter())) == len(list(out.iter()))


def test_xhtml_in_translated_text_is_preserved():
    pretty = CrfPrettyPrinter(SYNTHETIC).pretty_print_to_string()

    assert "<p>Record <b>all</b> medications taken.</p>" in pretty
    tree = etree.fromstring(pretty.encode("utf-8"))
    div = tree.find(f".//{{{XHTML_NS}}}div")
    assert div is not None
    assert div.find(f"{{{XHTML_NS}}}p").find(f"{{{XHTML_NS}}}b").text == "all"
    assert div.find(f"{{{XHTML_NS}}}p").find(f"{{{XHTML_NS}}}b").tail == " medications taken."


def test_comments_survive():
    assert "<!--" in CrfPrettyPrinter(SYNTHETIC).pretty_print_to_string()


def test_pretty_print_to_file(tmp_path: Path):
    out_file = tmp_path / "pretty.xml"
    CrfPrettyPrinter(SYNTHETIC).pretty_print_to_file(out_file)

    assert etree.parse(str(out_file)).getroot().tag.endswith("ODM")


def test_init_raises_when_file_missing(tmp_path: Path):
    with pytest.raises(CrfPrettyPrintError, match="not found"):
        CrfPrettyPrinter(tmp_path / "nope.xml")


def test_malformed_xml_raises(tmp_path: Path):
    bad_xml = tmp_path / "bad.xml"
    bad_xml.write_text("<ODM><broken></ODM>", encoding="utf-8")

    with pytest.raises(CrfPrettyPrintError, match="Unable to parse"):
        CrfPrettyPrinter(bad_xml).pretty_print_to_string()


def test_console_head(capsys):
    CrfPrettyPrinter(SYNTHETIC).pretty_print_to_console(head=10)

    assert len(capsys.readouterr().out.splitlines()) == 10


def test_console_full(capsys):
    pp = CrfPrettyPrinter(SYNTHETIC)
    pp.pretty_print_to_console()

    assert len(capsys.readouterr().out.splitlines()) == len(pp.pretty_print_to_string().splitlines())


def test_write_to_folder_is_reported(tmp_path: Path):
    with pytest.raises(CrfPrettyPrintError, match="write to a directory"):
        CrfPrettyPrinter(SYNTHETIC).pretty_print_to_file(tmp_path)


# the command

def test_cli_writes_the_file_and_exits_0(tmp_path, run_cli):
    completed = run_cli("crfpp", "-c", str(SYNTHETIC), "-o", str(tmp_path / "out.xml"))

    assert completed.returncode == 0
    assert (tmp_path / "out.xml").read_bytes() == CrfPrettyPrinter(SYNTHETIC).pretty_print_to_string().encode("utf-8")


def test_cli_head(run_cli):
    completed = run_cli("crfpp", "-c", str(SYNTHETIC), "-H", "5")

    assert completed.returncode == 0
    assert len(completed.stdout.splitlines()) == 5


def test_cli_missing_file_exits_2(tmp_path, run_cli):
    completed = run_cli("crfpp", "-c", str(tmp_path / "nope.xml"))

    assert completed.returncode == 2
    assert b"not found" in completed.stderr


def test_cli_write_to_folder_exits_2(tmp_path, run_cli):
    completed = run_cli("crfpp", "-c", str(SYNTHETIC), "-o", str(tmp_path))

    assert completed.returncode == 2
    assert b"write to a directory" in completed.stderr


def test_console_broken_pipe_exits_cleanly(cli_command, big_crf):
    # a reader that quits after one line closes the pipe early; the CLI exits 0 with no traceback
    p = _run_pp_console(cli_command("crfpp"), big_crf)
    try:
        p.stdout.readline()
        p.stdout.close()
        err = p.stderr.read()
        rc = p.wait(timeout=15)
    finally:
        if p.poll() is None:
            p.kill()
        p.stderr.close()

    assert rc == 0
    assert b"Traceback" not in err
    assert b"BrokenPipeError" not in err


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot send SIGINT to a child process; "
                    "test_entry_points covers run()'s Ctrl-C handling on every platform")
def test_console_ctrl_c_exits_cleanly(cli_command, big_crf):
    p = _run_pp_console(cli_command("crfpp"), big_crf)
    try:
        p.stdout.readline()          # the writer is now blocked on the full pipe
        time.sleep(0.3)
        assert p.poll() is None, "crfpp finished before Ctrl-C could be sent; the input is not large enough"
        p.send_signal(signal.SIGINT)
        rc = p.wait(timeout=15)
        err = p.stderr.read()
    finally:
        if p.poll() is None:
            p.kill()
        p.stdout.close()
        p.stderr.close()

    assert rc == 130
    assert b"Traceback" not in err
    assert b"KeyboardInterrupt" not in err
