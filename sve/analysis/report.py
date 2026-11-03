"""Build results/report.md and results/report.html from the same blocks."""

import html
import os

LIMITATIONS = [
    "Pedestrians stand still; nobody moves out of the way.",
    "Harm is a collision proxy: who was hit and at what speed. There is no injury model, "
    "and the ego's occupants are not scored.",
    "One map, one straight three-lane road, a small grid.",
    "LLM answers are nondeterministic; each prompt was answered once.",
    "Answers come from Claude models only (via Claude Code). They are not independent "
    "value sources, so agreement between them says little about people or other models.",
    "CARLA's pedestrian models are generic: ages and other attributes are metadata labels "
    "shown in prompts and captions, not visible in the images.",
    "The enacted prompt is a rendered text readout of simulator state, not raw sensor data "
    "or images; see docs/conditions.md for every difference from the stated prompts.",
]


class Report(object):
    def __init__(self, title):
        self.title = title
        self.blocks = []

    def h(self, level, text):
        self.blocks.append(("h", level, text))

    def p(self, text):
        self.blocks.append(("p", text))

    def ul(self, items):
        self.blocks.append(("ul", list(items)))

    def ol(self, items):
        self.blocks.append(("ol", list(items)))

    def table(self, rows, columns=None):
        if rows:
            columns = columns or list(rows[0].keys())
            self.blocks.append(("table", columns, [[r.get(c) for c in columns] for r in rows]))

    def img(self, path, caption):
        self.blocks.append(("img", path, caption))

    def link(self, path, text):
        self.blocks.append(("link", path, text))

    # ---- markdown -------------------------------------------------------

    def markdown(self):
        out = ["# " + self.title, ""]
        for b in self.blocks:
            kind = b[0]
            if kind == "h":
                out += ["#" * b[1] + " " + b[2], ""]
            elif kind == "p":
                out += [b[1], ""]
            elif kind in ("ul", "ol"):
                out += [("1. " if kind == "ol" else "- ") + item for item in b[1]] + [""]
            elif kind == "table":
                out.append("| " + " | ".join(b[1]) + " |")
                out.append("|" + "---|" * len(b[1]))
                for row in b[2]:
                    out.append("| " + " | ".join(_cell(v) for v in row) + " |")
                out.append("")
            elif kind == "img":
                out += ["![{}]({})".format(b[2], b[1]), "", "*{}*".format(b[2]), ""]
            elif kind == "link":
                out += ["[{}]({})".format(b[2], b[1]), ""]
        return "\n".join(out)

    # ---- html -----------------------------------------------------------

    def html(self):
        body = ["<h1>{}</h1>".format(html.escape(self.title))]
        for b in self.blocks:
            kind = b[0]
            if kind == "h":
                body.append("<h{0}>{1}</h{0}>".format(b[1], html.escape(b[2])))
            elif kind == "p":
                body.append("<p>{}</p>".format(_inline(b[1])))
            elif kind in ("ul", "ol"):
                body.append("<{0}>{1}</{0}>".format(kind, "".join(
                    "<li>{}</li>".format(_inline(i)) for i in b[1])))
            elif kind == "table":
                head = "".join("<th>{}</th>".format(html.escape(c)) for c in b[1])
                rows = "".join("<tr>{}</tr>".format("".join(
                    "<td>{}</td>".format(html.escape(_cell(v))) for v in row)) for row in b[2])
                body.append('<div class="scroll"><table><thead><tr>{}</tr></thead>'
                            "<tbody>{}</tbody></table></div>".format(head, rows))
            elif kind == "img":
                body.append('<figure><img src="{}" alt="{}"><figcaption>{}</figcaption>'
                            "</figure>".format(html.escape(b[1]), html.escape(b[2]),
                                               html.escape(b[2])))
            elif kind == "link":
                body.append('<p><a href="{}">{}</a></p>'.format(html.escape(b[1]),
                                                                html.escape(b[2])))
        return HTML_PAGE.format(title=html.escape(self.title), body="\n".join(body))

    def write(self, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        md = os.path.join(out_dir, "report.md")
        ht = os.path.join(out_dir, "report.html")
        with open(md, "w", encoding="utf-8", newline="\n") as f:
            f.write(self.markdown())
        with open(ht, "w", encoding="utf-8", newline="\n") as f:
            f.write(self.html())
        return md, ht


def _cell(v):
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return "%.3g" % v
    return str(v)


def _inline(text):
    """Escape, then render **bold** and `code` the way the markdown does."""
    out = html.escape(text)
    parts = out.split("**")
    out = "".join(("<strong>%s</strong>" % p) if i % 2 else p for i, p in enumerate(parts))
    parts = out.split("`")
    return "".join(("<code>%s</code>" % p) if i % 2 else p for i, p in enumerate(parts))


HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --line: #e4e3df; --accent: #2a78d6; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --line: #3a3936; --accent: #3987e5; }}
  img {{ background: #fcfcfb; }}
}}
body {{ background: var(--bg); color: var(--ink); margin: 0;
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 980px; margin: 0 auto; padding: 24px 16px 64px; }}
h1 {{ font-size: 26px; margin: 0 0 8px; }}
h2 {{ font-size: 19px; margin: 32px 0 8px; border-top: 1px solid var(--line); padding-top: 20px; }}
h3 {{ font-size: 16px; margin: 20px 0 6px; }}
p, li {{ color: var(--ink); }}
figcaption {{ color: var(--ink-2); font-size: 13px; margin-top: 4px; }}
figure {{ margin: 16px 0; }}
img {{ max-width: 100%; height: auto; border: 1px solid var(--line); border-radius: 4px; }}
.scroll {{ overflow-x: auto; }}
table {{ border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }}
th, td {{ border-bottom: 1px solid var(--line); padding: 4px 10px; text-align: left;
  white-space: nowrap; }}
th {{ color: var(--ink-2); font-weight: 600; }}
code {{ font: 13px ui-monospace, Consolas, monospace; }}
a {{ color: var(--accent); }}
</style>
</head>
<body><main>
{body}
</main></body>
</html>
"""
