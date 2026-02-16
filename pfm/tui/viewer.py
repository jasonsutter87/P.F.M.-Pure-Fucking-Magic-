"""PFM TUI Viewer - Main Textual app with 3-panel layout."""

from __future__ import annotations

import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Input

from pfm.reader import PFMReader, PFMReaderHandle
from pfm.tui.widgets import ContentPanel, MetadataPanel, SectionList


class PFMViewerApp(App):
    """TUI viewer for .pfm files. 3-panel layout with keyboard navigation."""

    TITLE = "PFM Viewer"
    CSS = """
    Screen {
        layout: vertical;
    }
    #main-area {
        height: 1fr;
    }
    #search-bar {
        dock: bottom;
        display: none;
        height: 3;
        padding: 0 1;
    }
    #search-bar.visible {
        display: block;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("slash", "toggle_search", "Search", show=True),
        Binding("escape", "close_search", "Close search", show=False),
        Binding("j", "next_section", "Next", show=True),
        Binding("k", "prev_section", "Prev", show=True),
    ]

    def __init__(self, pfm_path: str | Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._pfm_path = Path(pfm_path)
        self._reader: PFMReaderHandle | None = None
        self._section_names: list[str] = []
        self._all_section_names: list[str] = []

    def compose(self) -> ComposeResult:
        # Open the PFM file
        self._reader = PFMReader.open(self._pfm_path)
        self._section_names = list(self._reader.section_names)
        self._all_section_names = list(self._section_names)

        self.title = f"PFM Viewer - {self._pfm_path.name}"

        yield Header()

        with Horizontal(id="main-area"):
            yield MetadataPanel(
                meta=self._reader.meta,
                checksum_valid=self._reader.validate_checksum(),
                format_version=self._reader.format_version,
                id="metadata",
            )
            yield SectionList(
                section_names=self._section_names,
                id="sections",
            )
            yield ContentPanel(id="content")

        yield Input(placeholder="Search sections... (Escape to close)", id="search-bar")
        yield Footer()

    def on_mount(self) -> None:
        """Auto-select first section on mount."""
        if self._section_names and self._reader:
            content = self._reader.get_section(self._section_names[0])
            panel = self.query_one("#content", ContentPanel)
            panel.show_content(self._section_names[0], content or "")
            # Focus the section list for keyboard nav
            section_list = self.query_one("#sections", SectionList)
            section_list.focus()

    def on_section_list_section_selected(
        self, event: SectionList.SectionSelected
    ) -> None:
        """Handle section selection from the list."""
        if self._reader:
            content = self._reader.get_section(event.section_name)
            panel = self.query_one("#content", ContentPanel)
            panel.show_content(event.section_name, content or "")

    def action_next_section(self) -> None:
        """Move to next section."""
        section_list = self.query_one("#sections", SectionList)
        section_list.action_cursor_down()

    def action_prev_section(self) -> None:
        """Move to previous section."""
        section_list = self.query_one("#sections", SectionList)
        section_list.action_cursor_up()

    def action_toggle_search(self) -> None:
        """Show/hide the search bar."""
        search = self.query_one("#search-bar", Input)
        search.toggle_class("visible")
        if search.has_class("visible"):
            search.focus()
        else:
            search.value = ""
            self._restore_sections()
            self.query_one("#sections", SectionList).focus()

    def action_close_search(self) -> None:
        """Close the search bar."""
        search = self.query_one("#search-bar", Input)
        search.remove_class("visible")
        search.value = ""
        self._restore_sections()
        self.query_one("#sections", SectionList).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter sections as user types in search bar."""
        if event.input.id != "search-bar":
            return
        query = event.value.lower().strip()
        if not query:
            self._restore_sections()
            return
        # Filter section names
        filtered = [n for n in self._all_section_names if query in n.lower()]
        self._update_section_list(filtered)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle search submission - also search within section content."""
        if event.input.id != "search-bar":
            return
        query = event.value.lower().strip()
        if not query or not self._reader:
            return
        # Search both names and content
        matches = []
        for name in self._all_section_names:
            if query in name.lower():
                matches.append(name)
                continue
            content = self._reader.get_section(name) or ""
            if query in content.lower():
                matches.append(name)
        self._update_section_list(matches)

    def _update_section_list(self, names: list[str]) -> None:
        """Replace the section list with filtered names."""
        old = self.query_one("#sections", SectionList)
        new_list = SectionList(section_names=names, id="sections")
        old.remove()
        self.query_one("#main-area", Horizontal).mount(new_list, before="#content")
        if names and self._reader:
            content = self._reader.get_section(names[0])
            panel = self.query_one("#content", ContentPanel)
            panel.show_content(names[0], content or "")

    def _restore_sections(self) -> None:
        """Restore full section list."""
        self._update_section_list(self._all_section_names)

    def on_unmount(self) -> None:
        if self._reader:
            self._reader.close()
            self._reader = None


def run_viewer(path: str | Path) -> None:
    """Launch the PFM TUI viewer."""
    path = Path(path)
    if not path.exists():
        print(f"Error: File not found: {path}", file=sys.stderr)
        sys.exit(1)
    if not PFMReader.is_pfm(path):
        print(f"Error: Not a PFM file: {path}", file=sys.stderr)
        sys.exit(1)

    app = PFMViewerApp(path)
    app.run()
