# =========================================
# File: cadetgui/widgets/_chrome.py
# =========================================
from __future__ import annotations

from pathlib import Path

_CSS = (Path(__file__).parent / "chrome.css").read_text()


def style_tag() -> str:
    """Shared <style> HTML for composite/form widget chrome.

    See chrome.css for the class names (.cadetgui-panel, .cadetgui-section, ...).
    """
    return f"<style>{_CSS}</style>"
