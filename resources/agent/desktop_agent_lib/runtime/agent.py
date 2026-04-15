from __future__ import annotations

from .base import AgentRuntimeBase
from .conversions import ConversionPathMixin
from .desktop_tools import DesktopToolMixin
from .documents import DocumentFormatMixin
from .spreadsheets import SpreadsheetFormatMixin


class AgentRuntime(
    DesktopToolMixin,
    SpreadsheetFormatMixin,
    DocumentFormatMixin,
    ConversionPathMixin,
    AgentRuntimeBase,
):
    pass


__all__ = ["AgentRuntime"]
