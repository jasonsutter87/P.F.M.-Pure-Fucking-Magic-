"""PFM TUI Widgets - Custom panels for the PFM viewer."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static


class MetadataPanel(Static):
    """Sidebar panel showing PFM file metadata and checksum status."""

    DEFAULT_CSS = """
    MetadataPanel {
        width: 32;
        border: solid $accent;
        padding: 1;
        overflow-y: auto;
    }
    MetadataPanel .meta-title {
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }
    MetadataPanel .meta-key {
        color: $text-muted;
    }
    MetadataPanel .meta-val {
        color: $text;
        margin-bottom: 0;
    }
    MetadataPanel .checksum-valid {
        color: $success;
        text-style: bold;
    }
    MetadataPanel .checksum-invalid {
        color: $error;
        text-style: bold;
    }
    """

    def __init__(
        self,
        meta: dict[str, str],
        checksum_valid: bool,
        format_version: str,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._meta = meta
        self._checksum_valid = checksum_valid
        self._format_version = format_version

    def compose(self) -> ComposeResult:
        yield Label(f"PFM v{self._format_version}", classes="meta-title")

        # Checksum status
        if self._checksum_valid:
            yield Label("Checksum: VALID", classes="checksum-valid")
        else:
            yield Label("Checksum: INVALID", classes="checksum-invalid")

        yield Label("")  # spacer

        for key, val in self._meta.items():
            if key == "checksum":
                # Truncate long checksum
                display = val[:16] + "..." if len(val) > 16 else val
            elif len(val) > 24:
                display = val[:21] + "..."
            else:
                display = val
            yield Label(f"{key}:", classes="meta-key")
            yield Label(f"  {display}", classes="meta-val")


class SectionList(ListView):
    """List of sections in the PFM file. Supports keyboard navigation."""

    DEFAULT_CSS = """
    SectionList {
        width: 24;
        border: solid $accent;
    }
    SectionList > ListItem {
        padding: 0 1;
    }
    SectionList > ListItem.--highlight {
        background: $accent;
    }
    """

    class SectionSelected(Message):
        """Fired when a section is selected."""

        def __init__(self, section_name: str, section_index: int) -> None:
            self.section_name = section_name
            self.section_index = section_index
            super().__init__()

    def __init__(self, section_names: list[str], **kwargs) -> None:
        self._section_names = section_names
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        for name in self._section_names:
            yield ListItem(Label(name))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = self.index or 0
        if 0 <= idx < len(self._section_names):
            self.post_message(
                self.SectionSelected(self._section_names[idx], idx)
            )

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        idx = self.index or 0
        if 0 <= idx < len(self._section_names):
            self.post_message(
                self.SectionSelected(self._section_names[idx], idx)
            )


class ContentPanel(Static):
    """Main content viewer with syntax highlighting for code sections."""

    DEFAULT_CSS = """
    ContentPanel {
        border: solid $accent;
        padding: 1;
        overflow: auto;
    }
    ContentPanel .content-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    ContentPanel .content-body {
        color: $text;
    }
    """

    current_section = reactive("")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._title_widget: Label | None = None
        self._body_widget: Static | None = None

    def compose(self) -> ComposeResult:
        self._title_widget = Label("Select a section", classes="content-title")
        self._body_widget = Static("", classes="content-body")
        yield self._title_widget
        yield self._body_widget

    def show_content(self, name: str, content: str) -> None:
        """Display section content, with syntax highlighting for code blocks."""
        self.current_section = name
        if self._title_widget:
            self._title_widget.update(f"--- {name} ---")
        if self._body_widget:
            highlighted = self._try_highlight(name, content)
            self._body_widget.update(highlighted)
        self.scroll_home()

    def _try_highlight(self, name: str, content: str) -> str | object:
        """Attempt rich syntax highlighting for code-like sections."""
        # Map section names to likely languages
        code_hints = {
            "artifacts": "python",
            "tools": "python",
            "errors": "python",
        }
        lang = code_hints.get(name)

        # Auto-detect code blocks in content
        if lang is None and self._looks_like_code(content):
            lang = "python"

        if lang:
            try:
                from rich.syntax import Syntax
                return Syntax(content, lang, theme="monokai", line_numbers=True)
            except Exception:
                pass

        return content

    @staticmethod
    def _looks_like_code(content: str) -> bool:
        """Heuristic: does content look like code?"""
        code_indicators = [
            "def ", "class ", "import ", "from ", "return ",
            "function ", "const ", "let ", "var ",
            "SELECT ", "INSERT ", "CREATE ",
            "#!/",
        ]
        lines = content.split("\n")[:20]
        hits = sum(
            1 for line in lines
            for indicator in code_indicators
            if indicator in line
        )
        return hits >= 2
