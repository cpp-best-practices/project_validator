"""The TUI's app (see `project_validator.views.tui`), which needs textual: imported only when it is installed."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Header, Input, RichLog, Static, Tree
from textual.widgets.tree import TreeNode

from project_validator.analysis import Analysis, analyse
from project_validator.core import Check, Context, Progress, Status
from project_validator.views.common import fact_kinds, grouped, is_skipped, language_views
from project_validator.views.progress import STAGE_NAMES
from project_validator.views.tui import (
    detected,
    facts_page,
    language_page,
    markup,
    next_steps,
    overview,
    report_page,
    status_markup,
)


class NavTree(Tree[Any]):
    """The navigation tree, walked with the arrow keys as trees are elsewhere (upstream #389): Right expands a node,
    or moves to its first child once it is expanded; Left collapses it, or moves to its parent."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("right", "expand_or_enter", "Expand", show=False),
        Binding("left", "collapse_or_leave", "Collapse", show=False),
    ]

    def action_expand_or_enter(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.is_expanded and node.children:
            self.move_cursor(node.children[0])
        elif node.allow_expand:
            node.expand()

    def action_collapse_or_leave(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.is_expanded:
            node.collapse()
        elif node.parent is not None:
            self.move_cursor(node.parent)


def _add_results(results: TreeNode[Any], analysis: Analysis) -> None:
    """The results, a branch per category, and the checks that do not apply."""
    for group in grouped(analysis.reports):
        branch = results.add(f"{group.category} [dim]{len(group.reports)}[/]", data=("overview", None))
        for report in group.reports:
            branch.add_leaf(
                f"{status_markup(report.result.status)} {markup(report.check.name)}", data=("report", report)
            )
    skipped = [report for report in analysis.reports if is_skipped(report)]
    if skipped:
        branch = results.add(f"Not applicable [dim]{len(skipped)}[/]", data=("overview", None))
        for report in skipped:
            branch.add_leaf(f"{status_markup(Status.SKIP)} {markup(report.check.name)}", data=("report", report))


class Validator(App[int]):
    """Analyses the project in a worker, telling each stage as it finishes, then shows the analysis."""

    CSS = """
    #loading { height: 1fr; border: round $accent; padding: 1 2; }
    #main { height: 1fr; }
    #nav { width: 38; border-right: solid $panel; }
    #pane { padding: 1 2; }
    #search { display: none; }
    #search.shown { display: block; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("slash", "search", "Search the facts"),
        Binding("escape", "close_search", "Close the search", show=False),
    ]
    TITLE = "project_validator"

    def __init__(self, context: Context, checks: Sequence[Check], every_check: Sequence[str]) -> None:
        super().__init__()
        self.context, self.checks, self.every_check = context, checks, every_check
        self.analysis: Analysis | None = None
        self.kind: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(id="loading", markup=True, wrap=True)
        with Horizontal(id="main"):
            yield NavTree("project", id="nav")
            with VerticalScroll():
                yield Input(placeholder="Search the facts…", id="search")
                yield Static("", id="pane")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#main").display = False
        log = self.query_one("#loading", RichLog)
        log.write(f"[bold]Reading[/] {markup(self.context.project.root)}")
        self.run_worker(self._analyse, thread=True)

    def _analyse(self) -> None:
        def progress(event: Progress) -> None:
            self.call_from_thread(self._progress, event)

        found = analyse(self.context, self.checks, every_check=self.every_check, progress=progress)
        self.call_from_thread(self._show, found)

    def _progress(self, event: Progress) -> None:
        log = self.query_one("#loading", RichLog)
        if event.kind == "stage" and event.done:
            name = STAGE_NAMES.get(event.name, event.name)
            log.write(f"[green]✔[/] {markup(name)} [dim]{event.found:,} facts, {event.seconds:.2f} s[/]")
        elif event.kind == "check" and event.done and event.index == event.total:
            log.write(f"[green]✔[/] Ran {event.total} checks")

    def _show(self, analysis: Analysis) -> None:
        self.analysis = analysis
        self.sub_title = analysis.score.summary() if analysis.score else analysis.name
        self.query_one("#loading").display = False
        self.query_one("#main").display = True
        tree = self.query_one("#nav", Tree)
        tree.root.set_label(analysis.name)
        tree.root.data = ("overview", None)
        tree.root.add_leaf("Overview", data=("overview", None))
        tree.root.add_leaf("What was detected", data=("detected", None))
        _add_results(tree.root.add("Results", data=("overview", None), expand=True), analysis)
        languages = tree.root.add("Languages", data=("detected", None))
        for view in language_views(analysis):
            languages.add_leaf(
                f"{markup(view.language)} [dim]{markup(view.files)}[/]", data=("language", view.language)
            )
        tree.root.add_leaf("Next steps", data=("next", None))
        facts = tree.root.add(f"Facts [dim]{len(analysis.facts.all):,}[/]", data=("facts", None))
        for kind, count in fact_kinds(analysis):
            facts.add_leaf(f"{markup(kind)} [dim]{count:,}[/]", data=("facts", kind))
        tree.root.expand()
        tree.focus()
        self._page("overview", None)

    def _page(self, page: str, value: Any) -> None:
        if self.analysis is None:
            return
        pane = self.query_one("#pane", Static)
        search = self.query_one("#search", Input)
        if page == "facts":
            self.kind = value
            pane.update(facts_page(self.analysis, value, search.value))
            return
        if page == "language":
            pane.update(language_page(self.analysis, value))
            return
        text = {
            "overview": overview,
            "detected": detected,
            "next": next_steps,
        }.get(page)
        pane.update(text(self.analysis) if text is not None else report_page(value))

    def on_tree_node_selected(self, event: Tree.NodeSelected[Any]) -> None:
        if event.node.data is not None:
            self._page(*event.node.data)

    def on_input_changed(self, event: Input.Changed) -> None:
        if self.analysis is not None:
            self.query_one("#pane", Static).update(facts_page(self.analysis, self.kind, event.value))

    def action_search(self) -> None:
        search = self.query_one("#search", Input)
        search.add_class("shown")
        search.focus()
        if self.analysis is not None:
            self.query_one("#pane", Static).update(facts_page(self.analysis, self.kind, search.value))

    def action_close_search(self) -> None:
        search = self.query_one("#search", Input)
        search.remove_class("shown")
        self.query_one("#nav", Tree).focus()
