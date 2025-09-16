import ipywidgets as W
from abc import ABC, abstractmethod
from typing import Optional

__all__ = ["BaseWidget"]


class BaseWidget(ABC):
    """Base widget providing a header, status, and a container layout."""

    def __init__(self, *, title: Optional[str] = None) -> None:
        """
        Initialize the widget container.

        Parameters
        ----------
        title : str, optional
            Title shown in the header, defaults to the class name.
        """
        self.title = title or self.__class__.__name__
        self._status = W.HTML("<em>Ready.</em>")
        self._header = W.HTML(f"<h3 style='margin:0'>{self.title}</h3>")
        self._body = self._build_body()
        self.root = W.VBox([self._header, self._body, self._status])
        self._wire_events()

    @abstractmethod
    def _build_body(self) -> W.Widget:
        """Create and return the main widget body."""

    def _wire_events(self) -> None:
        """Connect event handlers (optional, override in subclasses)."""

    def set_status(self, text: str) -> None:
        """Update the status display with a text message."""
        self._status.value = text

    def display(self) -> None:
        """Render the widget in a Jupyter notebook."""
        from IPython.display import display as _display
        _display(self.root)
