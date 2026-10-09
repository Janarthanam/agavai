"""Native rich-text formatting without scripts, styles or remote embeds."""
from html import escape
from html.parser import HTMLParser
import re
from urllib.parse import urlparse


class FormattingParser(HTMLParser):
    tags = {"p", "br", "b", "strong", "i", "em", "u", "pre", "code", "ul", "ol", "li", "h1", "h2", "h3", "blockquote", "a"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.blocked = 0
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "object"}:
            self.blocked += 1
        if self.blocked or tag not in self.tags:
            return
        extra = ""
        if tag == "a":
            href = dict(attrs).get("href", "")
            parsed = urlparse(href)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                return
            extra = f' href="{escape(href, quote=True)}"'
        self.parts.append(f"<{tag}{extra}>")
        if tag != "br":
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "iframe", "object"}:
            self.blocked = max(0, self.blocked - 1)
            return
        if not self.blocked and tag in self.stack:
            while self.stack:
                current = self.stack.pop()
                self.parts.append(f"</{current}>")
                if current == tag:
                    break

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(escape(data))

    def finish(self):
        while self.stack:
            self.parts.append(f"</{self.stack.pop()}>")
        return "".join(self.parts)


def rich_text(text: str, kind: str = "markdown") -> str:
    if kind == "plain":
        return "<p>" + escape(text).replace("\n", "<br>") + "</p>"
    if kind == "html":
        parser = FormattingParser()
        parser.feed(text)
        return parser.finish()
    parts = []
    code = False
    for line in text.splitlines():
        if line.startswith("```"):
            parts.append("</pre>" if code else "<pre>")
            code = not code
            continue
        if code:
            parts.append(escape(line) + "\n")
            continue
        safe = escape(line)
        safe = re.sub(r"`([^`]+)`", r"<code>\1</code>", safe)
        safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
        if line.startswith("# "):
            parts.append("<h2>" + safe[2:] + "</h2>")
        elif line.startswith(("## ", "### ")):
            parts.append("<h3>" + safe.lstrip("# ") + "</h3>")
        elif line.startswith("- "):
            parts.append("<p>• " + safe[2:] + "</p>")
        elif line:
            parts.append("<p>" + safe + "</p>")
    if code:
        parts.append("</pre>")
    return "".join(parts)


def pango_text(html: str) -> str:
    text = re.sub(r"<h[123]>", "<b>", html)
    text = re.sub(r"</h[123]>", "</b>\n\n", text)
    text = text.replace("<br>", "\n").replace("<p>", "").replace("</p>", "\n\n")
    for tag in ("code", "pre"):
        text = text.replace(f"<{tag}>", "<tt>").replace(f"</{tag}>", "</tt>")
    for tag in ("ul", "ol", "blockquote"):
        text = text.replace(f"<{tag}>", "").replace(f"</{tag}>", "\n")
    return text.replace("<li>", "• ").replace("</li>", "\n").replace("<strong>", "<b>").replace("</strong>", "</b>").replace("<em>", "<i>").replace("</em>", "</i>").strip()
