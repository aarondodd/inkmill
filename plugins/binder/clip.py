"""Turn a web page into a Markdown research note. Standard library only.

Keeps the page's main text (the ``<article>`` or ``<main>`` element when
there is one): headings, paragraphs, lists, quotes, emphasis, links and
code. Navigation, scripts, forms and footers are dropped.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe", "button", "select", "template"}
BLOCK = {"p", "div", "section", "article", "main", "li", "ul", "ol", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6",
         "table", "tr", "figure", "figcaption", "dl", "dt", "dd", "hr", "br"}
VOID = {"br", "hr", "img", "input", "meta", "link", "source", "wbr", "area", "base", "col", "embed", "param", "track"}


class _Converter(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.out: list[str] = []
        self.skip = 0
        self.lists: list[list] = []  # [kind, counter]
        self.quotes: list[int] = []  # start index into self.out of each open blockquote
        self.pre = 0
        self.href: list[str | None] = []
        self.title = ""
        self._in_title = False

    def _newline(self, count: int = 2) -> None:
        text = "".join(self.out)
        trailing = len(text) - len(text.rstrip("\n"))
        if text and trailing < count:
            self.out.append("\n" * (count - trailing))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self._in_title = True
        if self.skip or tag in SKIP:
            if tag not in VOID:
                self.skip += 1
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._newline()
            self.out.append("#" * int(tag[1]) + " ")
        elif tag in ("p", "div", "section", "figure", "table", "dl"):
            self._newline()
        elif tag in ("ul", "ol"):
            self._newline(1 if self.lists else 2)
            self.lists.append([tag, 0])
        elif tag == "li":
            self._newline(1)
            depth = max(0, len(self.lists) - 1)
            if self.lists and self.lists[-1][0] == "ol":
                self.lists[-1][1] += 1
                self.out.append("   " * depth + f"{self.lists[-1][1]}. ")
            else:
                self.out.append("  " * depth + "- ")
        elif tag == "blockquote":
            self._newline()
            self.quotes.append(len(self.out))
        elif tag == "pre":
            self._newline()
            self.out.append("```\n")
            self.pre += 1
        elif tag == "code" and not self.pre:
            self.out.append("`")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag == "a":
            href = attrs.get("href")
            if href and not href.startswith(("javascript:", "#")):
                self.out.append("[")
                self.href.append(urllib.parse.urljoin(self.base, href))
            else:
                self.href.append(None)
        elif tag == "br":
            self.out.append("  \n")
        elif tag == "hr":
            self._newline()
            self.out.append("---")
            self._newline()
        elif tag == "img":
            alt = (attrs.get("alt") or "").strip()
            src = attrs.get("src")
            if src and alt:
                self.out.append(f"![{alt}]({urllib.parse.urljoin(self.base, src)})")
        elif tag == "tr":
            self._newline(1)
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if self.skip:
            if tag in SKIP or tag not in VOID:
                self.skip -= 1 if self.skip else 0
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "section", "figure", "table", "dl"):
            self._newline()
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            self._newline()
        elif tag == "blockquote" and self.quotes:
            start = self.quotes.pop()
            inner = "".join(self.out[start:]).strip("\n")
            del self.out[start:]
            self.out.append("\n".join(("> " + line) if line.strip() else ">" for line in inner.split("\n")))
            self._newline()
        elif tag == "pre":
            self.pre = max(0, self.pre - 1)
            self._newline(1)
            self.out.append("```")
            self._newline()
        elif tag == "code" and not self.pre:
            self.out.append("`")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag == "a" and self.href:
            href = self.href.pop()
            if href:
                self.out.append(f"]({href})")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self.skip:
            return
        if self.pre:
            self.out.append(data)
        else:
            self.out.append(re.sub(r"\s+", " ", data))


def _main_part(html: str) -> str:
    for tag in ("article", "main"):
        match = re.search(rf"<{tag}\b[^>]*>(.*)</{tag}>", html, re.IGNORECASE | re.DOTALL)
        if match and len(re.sub(r"<[^>]+>", "", match.group(1)).strip()) > 200:
            return match.group(1)
    match = re.search(r"<body\b[^>]*>(.*)</body>", html, re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else html


def to_markdown(html: str, base_url: str = "") -> tuple[str, str]:
    """(title, Markdown body) for a page of HTML."""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
    converter = _Converter(base_url)
    converter.feed(_main_part(html))
    converter.close()
    text = "".join(converter.out)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\*\*\s*\*\*", "", text)
    text = re.sub(r"\[\s*\]\([^)]*\)", "", text)
    import html as html_lib

    return html_lib.unescape(title), text.strip() + "\n"


def fetch(url: str, timeout: int = 20) -> tuple[str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Inkmill web clipper)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(5_000_000)
        charset = response.headers.get_content_charset() or "utf-8"
    return to_markdown(raw.decode(charset, errors="replace"), url)
