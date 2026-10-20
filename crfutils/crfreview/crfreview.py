"""
Renders an ODM v2.0 CRF with crfhtml, writes the HTML and opens it in the default browser: what double-clicking a
CRF runs once crfreview has been chosen to open it. A port of defineutils' defineview.
"""
import hashlib
import html
import os
import tempfile
import webbrowser
from pathlib import Path

from crfutils import __version__
from crfutils.crfhtml import CrfHtml, CrfHtmlWriteError

ISSUES = "https://github.com/swhume/crfutils/issues"

# the page shown instead of the HTML when the CRF can't be shown
ERROR_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{heading}</title>
<style>
body {{ font-family: Arial, sans-serif; max-width: 60em; margin: 2em auto; padding: 0 1em; line-height: 1.5; }}
pre {{ white-space: pre-wrap; background: #f4f4f4; padding: 1em; }}
</style>
</head>
<body>
<h1>{heading}</h1>
{advice}
<pre>{message}</pre>
{link}
<p>crfreview {version}</p>
</body>
</html>
"""


class CrfViewError(Exception):
    """the HTML, or the page saying why there is none, could not be written or opened"""
    pass


class CrfViewer:
    def __init__(self, crf_file: Path, temp: bool = False, out_file: Path = None) -> None:
        """
        :param crf_file: Path to the CRF to show
        :param temp: when True, the HTML is written to temp_folder rather than beside the CRF
        :param out_file: when given, the HTML is written there; it can't be combined with temp
        """
        if temp and out_file is not None:
            raise CrfViewError("Choose the temp folder or an output file, not both.")
        self.crf_file = Path(crf_file)
        self.temp = temp
        self.out_file = None if out_file is None else Path(out_file)

    @property
    def temp_folder(self) -> Path:
        """
        this CRF's folder in the per-user temp folder, <temp>/crfutils/<12 hex digits>, named from a hash of the
        CRF's path, so each CRF has its own and showing it again overwrites it
        """
        key = hashlib.sha256(_folder_key(self.crf_file).encode("utf-8")).hexdigest()[:12]
        return Path(tempfile.gettempdir(), "crfutils", key)

    def write_html(self) -> Path:
        """
        renders the CRF and writes the HTML: to out_file; with temp, to temp_folder; otherwise beside the CRF as
        <name>.html, replacing any file there, or to temp_folder when it can't be written there. The HTML has
        only #fragment links, so it works wherever it is saved
        :return: the path of the HTML
        :raises CrfHtmlGenerationError: the CRF could not be rendered, or the HTML could not be written
        """
        if self.out_file is not None:
            return self._write(self.out_file)
        if not self.temp:
            try:
                return self._write(self.crf_file.with_suffix(".html"))
            except CrfHtmlWriteError:
                # a read-only share, an email attachment's folder: the HTML goes to the temp folder instead
                pass
        folder = self.temp_folder
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise CrfHtmlWriteError(f"Unable to create the folder {folder}.\n{e}") from e
        return self._write(folder / f"{self.crf_file.stem}.html")

    def write_error_page(self, message: str, unexpected: bool = False) -> Path:
        """
        writes the page saying why the CRF was not shown to <name>.error.html in temp_folder, never beside the
        CRF, with a link that shows the file as plain XML in the browser when it exists
        :param message: why it was not shown: the error message, or for an unexpected error the traceback
        :param unexpected: when True, the page asks for the error to be reported
        :return: the path of the page
        :raises CrfViewError: the page could not be written
        """
        name = html.escape(self.crf_file.name)
        if unexpected:
            heading = f"crfreview failed unexpectedly while showing {name}"
            advice = f'<p>Please report this, with the details below, at <a href="{ISSUES}">{ISSUES}</a>.</p>'
        else:
            heading, advice = f"{name} could not be shown", ""
        try:
            exists = self.crf_file.is_file()
        except OSError:
            exists = False
        # a link the browser follows itself: handing an .xml file to the operating system would start crfreview
        # again when it is the default for .xml files
        link = (f'<p><a href="{html.escape(_absolute(self.crf_file).as_uri())}">View {name} as plain XML</a></p>'
                if exists else "")
        page = ERROR_PAGE.format(heading=heading, advice=advice, message=html.escape(message.rstrip()), link=link,
                                 version=__version__)
        path = self.temp_folder / f"{self.crf_file.stem}.error.html"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(page, encoding="utf-8")
        except OSError as e:
            raise CrfViewError(f"Unable to write {path}.\n{e}") from e
        return path

    def _write(self, html_file: Path) -> Path:
        """renders the CRF to html_file with crfhtml's default options"""
        CrfHtml(self.crf_file).transform_to_html_file(html_file)
        return html_file


def open_in_browser(page: Path) -> None:
    """
    opens an HTML page in the default browser; on Windows, webbrowser hands its URL to the program that opens .html
    files. Only ever pass it an .html page: an .xml file would start crfreview again when it is the default for .xml
    :param page: the page to open
    :raises CrfViewError: no browser could be started
    """
    if not webbrowser.open(_absolute(page).as_uri()):
        raise CrfViewError(f"No browser could be started to show {page}. Open that file in a browser.")


def _absolute(path: Path) -> Path:
    """the absolute path; abspath, not resolve(), which turns a mapped network drive into its UNC path"""
    return Path(os.path.abspath(path))


def _folder_key(path: Path) -> str:
    """a path in one spelling, for comparing paths: absolute, and on Windows lower case with \\ separators"""
    return os.path.normcase(os.path.abspath(path))
