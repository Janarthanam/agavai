"""Write RUN_DIR/report.html: the page reads the report data embedded in it,
and can open any other report.json dropped on it."""

from __future__ import annotations

from pathlib import Path

TEMPLATE = Path(__file__).with_name("report_template.html")
PLACEHOLDER = "__REPORT_DATA__"


def write_html(run_dir: Path) -> Path:
    data = (run_dir / "report.json").read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")
    # A literal "</" would end the script element that carries the data.
    page = template.replace(PLACEHOLDER, data.replace("</", "<\\/"), 1)
    out = run_dir / "report.html"
    out.write_text(page, encoding="utf-8")
    return out
