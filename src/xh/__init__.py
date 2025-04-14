"""Xhell."""

import sys

from importlib import metadata as importlib_metadata
from typing import cast

# On non-Windows platforms, try to use sh; otherwise, use xh.core.
if sys.platform != 'win32':
    try:
        import sh

        Command = sh.Command
        xh = sh
    except ImportError:
        from xh.core import Command, xh
else:
    from xh.core import Command, xh


def get_version() -> str:
    """Return the program version."""
    try:
        return importlib_metadata.version(__name__)
    except importlib_metadata.PackageNotFoundError:  # pragma: no cover
        return '0.2.1'  # semantic-release


version = get_version()

__version__ = version
__author__ = 'Ivan Ogasawara'
__email__ = 'ivan.ogasawara@gmail.com'

__all__ = ['Command', 'xh']


def __getattr__(name: str) -> Command:  # type: ignore[valid-type]
    try:
        return cast(Command, getattr(xh, name))  # type: ignore[valid-type]
    except AttributeError:
        raise AttributeError(f'module {__name__} has no attribute {name}')
