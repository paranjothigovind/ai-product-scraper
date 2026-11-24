"""A small, forgiving DOM built on html.parser. Never raises on malformed input and is bounded
in depth and node count so hostile pages cannot exhaust memory or the stack."""

from collections.abc import Iterator
from html.parser import HTMLParser

DOCUMENT = "#document"
TEXT = "#text"

VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param"}
    | {"source", "track", "wbr"}
)

_BLOCKS_CLOSING_P = frozenset(
    {"address", "article", "aside", "blockquote", "div", "dl", "fieldset", "footer", "form"}
    | {"h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "main", "nav", "ol", "p", "pre"}
    | {"section", "table", "ul"}
)

# Opening the key tag implicitly closes an open element from the value set.
_AUTO_CLOSE: dict[str, frozenset[str]] = {
    "li": frozenset({"li"}),
    "dt": frozenset({"dt", "dd"}),
    "dd": frozenset({"dt", "dd"}),
    "tr": frozenset({"tr", "td", "th"}),
    "td": frozenset({"td", "th"}),
    "th": frozenset({"td", "th"}),
    "option": frozenset({"option"}),
    "thead": frozenset({"thead", "tbody", "tfoot", "tr", "td", "th"}),
    "tbody": frozenset({"thead", "tbody", "tfoot", "tr", "td", "th"}),
    "tfoot": frozenset({"thead", "tbody", "tfoot", "tr", "td", "th"}),
    **{tag: frozenset({"p"}) for tag in _BLOCKS_CLOSING_P},
}
# Implicit closing never reaches past these.
_SCOPE_BOUNDARIES = frozenset(
    {"ul", "ol", "dl", "table", "select", "html", "body", "template", "tbody", "thead", "tfoot"}
)


class Node:
    __slots__ = ("attrs", "children", "parent", "tag", "text")

    def __init__(
        self,
        tag: str,
        attrs: dict[str, str] | None = None,
        text: str = "",
        parent: "Node | None" = None,
    ) -> None:
        self.tag = tag
        self.attrs: dict[str, str] = attrs if attrs is not None else {}
        self.children: list[Node] = []
        self.text = text
        self.parent = parent

    @property
    def is_element(self) -> bool:
        return not self.tag.startswith("#")

    @property
    def classes(self) -> frozenset[str]:
        return frozenset(self.attrs.get("class", "").split())

    def get(self, name: str) -> str | None:
        return self.attrs.get(name)

    def descendants(self) -> Iterator["Node"]:
        """Document-order traversal; iterative so depth never hits the recursion limit."""
        stack = list(reversed(self.children))
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))

    def elements(self, tag: str | None = None) -> Iterator["Node"]:
        for node in self.descendants():
            if node.is_element and (tag is None or node.tag == tag):
                yield node

    def ancestors(self) -> Iterator["Node"]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def text_content(self) -> str:
        """All descendant text, including script/style bodies (use html.text for visible text)."""
        return "".join(n.text for n in self.descendants() if n.tag == TEXT)

    def __repr__(self) -> str:
        return f"Node({self.tag!r}, {len(self.children)} children)"


class Document:
    __slots__ = ("root", "truncated")

    def __init__(self, root: Node, truncated: bool) -> None:
        self.root = root
        self.truncated = truncated  # True when the node cap cut parsing short


class _Stop(Exception):
    pass


class _Builder(HTMLParser):
    def __init__(self, max_nodes: int, max_depth: int) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node(DOCUMENT)
        self.stack: list[Node] = [self.root]
        self.count = 0
        self.max_nodes = max_nodes
        self.max_depth = max_depth
        self.truncated = False
        # Elements opened past max_depth are attached but never pushed; their end tags are
        # swallowed here so they cannot close real ancestors.
        self.overflow: dict[str, int] = {}

    def _attach(self, node: Node) -> None:
        self.count += 1
        if self.count > self.max_nodes:
            self.truncated = True
            raise _Stop
        parent = self.stack[-1]
        node.parent = parent
        parent.children.append(node)

    def _auto_close(self, tag: str) -> None:
        closers = _AUTO_CLOSE.get(tag)
        if closers is None:
            return
        lowest = None
        for i in range(len(self.stack) - 1, 0, -1):
            name = self.stack[i].tag
            if name in closers:
                lowest = i
            elif name in _SCOPE_BOUNDARIES:
                break
        if lowest is not None:
            self._pop_to(lowest)

    def _pop_to(self, index: int) -> None:
        del self.stack[index:]
        self.overflow.clear()

    def _open(self, tag: str, attrs: list[tuple[str, str | None]], *, void: bool) -> None:
        self._auto_close(tag)
        node = Node(tag)
        for name, value in attrs:
            node.attrs.setdefault(name, value or "")  # first duplicate wins, as in browsers
        self._attach(node)
        if void:
            return
        if len(self.stack) >= self.max_depth:
            self.overflow[tag] = self.overflow.get(tag, 0) + 1
        else:
            self.stack.append(node)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, attrs, void=tag in VOID_TAGS)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, attrs, void=True)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        if self.overflow.get(tag, 0) > 0:
            self.overflow[tag] -= 1
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                self._pop_to(i)
                return
        # Stray end tag: ignored.

    def handle_data(self, data: str) -> None:
        if not data:
            return
        top = self.stack[-1]
        last = top.children[-1] if top.children else None
        if last is not None and last.tag == TEXT:
            last.text += data
            return
        self._attach(Node(TEXT, text=data))


def parse_html(html: str, *, max_nodes: int = 200_000, max_depth: int = 256) -> Document:
    builder = _Builder(max_nodes, max_depth)
    try:
        builder.feed(html.replace("\x00", ""))
        builder.close()
    except _Stop:
        pass
    return Document(builder.root, builder.truncated)
