"""CLI and I/O plumbing shared by every crfutils command.

Each command's ``__main__.run()`` is ``_common.run(main)``, so the Ctrl-C and broken-pipe handling
lives in one place; every writer goes through ``write_text`` / ``write_bytes``, so a folder given as an
output file is reported as a folder on every platform.
"""
import os
import sys
from pathlib import Path
from typing import Callable, Iterable, Union


def _quiet_exit(code: int) -> None:
    """Terminate immediately via os._exit, bypassing interpreter shutdown, so a late write to a closed
    pipe -- or a Ctrl-C during finalization -- cannot print an 'Exception ignored ...' message or
    traceback at exit. 130 == 128 + SIGINT, the conventional Ctrl-C status; a broken pipe exits 0 since
    quitting the pager is not an error. A module attribute so the tests can swap it for sys.exit."""
    os._exit(code)


def run(main: Callable[[], Union[int, None]]) -> None:
    """
    the body of every command's run(): exits with main()'s code, 130 on Ctrl-C and 0 on a closed pipe.
    The console scripts call run() directly, never a module's __main__ block, so this is where the
    handling must stay
    :param main: the command's main(), which returns the exit code
    """
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        _quiet_exit(130)
    except BrokenPipeError:
        _quiet_exit(0)


def require_file(path: Path, error_cls: type) -> None:
    """
    confirms that an input file exists before any work starts
    :param path: the input file
    :param error_cls: the exception class to raise
    """
    path = Path(path)
    try:
        exists = path.is_file()
    except OSError as e:
        raise error_cls(f"Unable to access {path}.\n{e}") from e
    if not exists:
        raise error_cls(f"File {path} not found.")


def write_bytes(path: Path, data: bytes, error_cls: type) -> None:
    """
    writes bytes to path, mapping the OS errors onto error_cls with the defineutils wording
    :param path: the file to write
    :param data: the bytes to write
    :param error_cls: the exception class to raise
    """
    try:
        with open(path, "wb") as f:
            f.write(data)
    except FileNotFoundError as e:
        raise error_cls(f"File {path} not found.\n{e}") from e
    except PermissionError as e:
        # Windows raises PermissionError, not IsADirectoryError, for a folder; os.path.isdir never raises,
        # where Path.is_dir() can when a parent folder is unreadable
        if os.path.isdir(path):
            raise error_cls(f"Error attempting to write to a directory {path}.") from e
        raise error_cls(f"Permission error attempting to write to {path}.\n{e}") from e
    except IsADirectoryError as e:
        raise error_cls(f"Error attempting to write to a directory {path}.\n{e}") from e
    except OSError as e:
        raise error_cls(f"Unable to write {path}.\n{e}") from e


def write_text(path: Path, text: str, error_cls: type) -> None:
    """
    writes text to path, UTF-8 encoded, mapping the OS errors onto error_cls
    :param path: the file to write
    :param text: the text to write
    :param error_cls: the exception class to raise
    """
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except FileNotFoundError as e:
        raise error_cls(f"File {path} not found.\n{e}") from e
    except PermissionError as e:
        if os.path.isdir(path):
            raise error_cls(f"Error attempting to write to a directory {path}.") from e
        raise error_cls(f"Permission error attempting to write to {path}.\n{e}") from e
    except IsADirectoryError as e:
        raise error_cls(f"Error attempting to write to a directory {path}.\n{e}") from e
    except OSError as e:
        raise error_cls(f"Unable to write {path}.\n{e}") from e


def check_destination(out: Path, inputs: Iterable[Path], error_cls: type) -> None:
    """
    refuses an output path that is one of the inputs (writing there would overwrite it), is a
    directory, or is in a directory that does not exist. Called before any transform runs
    :param out: the output file
    :param inputs: the input files it must not be
    :param error_cls: the exception class to raise
    """
    out = Path(out)
    try:
        for source in inputs:
            source = Path(source)
            if out.exists() and source.exists() and out.samefile(source):
                raise error_cls(f"The output file {out} is the input file {source}; writing there would "
                                f"overwrite it. Choose a different output file.")
        if out.is_dir():
            raise error_cls(f"Error attempting to write to a directory {out}.")
        if not out.parent.is_dir():
            raise error_cls(f"The output directory {out.parent} does not exist or is not a directory.")
    except OSError as e:
        raise error_cls(f"Unable to access the output file {out}.\n{e}") from e


def display_path(path: str, single_study: bool = True) -> str:
    """
    trims the constant ODM prefix from a collected path, and the Study[...] segment when the document
    has exactly one Study, so displayed paths start at the MetaDataVersion
    :param path: the collected path, e.g. "/ODM/Study[ST.1]/MetaDataVersion[MDV.1]/ItemDef[IT.1]"
    :param single_study: True when the document has one Study
    :return: string
    """
    segments = [s for s in path.split("/") if s]
    while segments and (segments[0] == "ODM"
                        or (single_study and segments[0].split("[")[0] == "Study")):
        segments.pop(0)
    return "/".join(segments) or "(document root)"
