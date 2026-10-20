"""crfutils: CDISC ODM v2.0 CRF utilities.

Only the version lives here. The subpackages are imported by name (``crfutils.crfhtml``, ...), never
eagerly: crfpdf's dependencies (WeasyPrint, pypdf) are optional and must not be imported by the
other commands.
"""
__version__ = "0.1.0"

__all__ = ["__version__"]
