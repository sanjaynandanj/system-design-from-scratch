"""Build site/phases/*.html from phases/*/README.md.

Converts each phase's markdown into a styled reader page matching the
site theme, with an anchor per lesson (#lesson-NN) and prev/next links.
Run from repo root: python scripts/build_site.py
"""
import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PHASES_DIR = ROOT / "phases"
OUT_DIR = ROOT / "site" / "phases"


def inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def md_to_html(md):
    out = []
    lines = md.split("\n")
    i = 0
    lesson_re = re.compile(r"^## (\d+)\.\s*(.*)")
    para = []

    def flush_para():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]

        if line.startswith("```"):
            flush_para()
            i += 1
            code = []
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            out.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
            i += 1
            continue

        m = lesson_re.match(line)
        if m:
            flush_para()
            num, title = m.group(1), m.group(2)
            out.append(f'<h2 id="lesson-{num}"><span class="lnum">{num}</span> {inline(title)}</h2>')
            i += 1
            continue

        if line.startswith("### "):
            flush_para()
            out.append("<h3>" + inline(line[4:]) + "</h3>")
            i += 1
            continue
        if line.startswith("## "):
            flush_para()
            out.append("<h2>" + inline(line[3:]) + "</h2>")
            i += 1
            continue
        if line.startswith("# "):
            flush_para()
            i += 1  # page has its own H1
            continue

        if line.startswith(">"):
            flush_para()
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i].lstrip("> "))
                i += 1
            out.append("<blockquote>" + inline(" ".join(quote)) + "</blockquote>")
            continue

        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|?\s*$", lines[i + 1]):
            flush_para()
            headers = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            t = "<table><thead><tr>" + "".join(f"<th>{inline(h)}</th>" for h in headers) + "</tr></thead><tbody>"
            for r in rows:
                t += "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
            out.append(t + "</tbody></table>")
            continue

        if re.match(r"^\s*[-*] ", line):
            flush_para()
            items = []
            while i < len(lines) and re.match(r"^\s*[-*] ", lines[i]):
                items.append(re.sub(r"^\s*[-*] ", "", lines[i]))
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(it)}</li>" for it in items) + "</ul>")
            continue

        if re.match(r"^\s*\d+\. ", line):
            flush_para()
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\. ", lines[i]):
                items.append(re.sub(r"^\s*\d+\. ", "", lines[i]))
                i += 1
            out.append("<ol>" + "".join(f"<li>{inline(it)}</li>" for it in items) + "</ol>")
            continue

        if re.match(r"^-{3,}\s*$", line):
            flush_para()
            out.append("<hr>")
            i += 1
            continue

        if line.strip() == "":
            flush_para()
            i += 1
            continue

        para.append(line.strip())
        i += 1

    flush_para()
    return "\n".join(out)


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — System Design From Scratch</title>
<style>
  :root {{
    --bg: #0b0e14; --bg-alt: #11151f; --card: #151a26; --border: #232a3b;
    --text: #d8dee9; --muted: #8892a6; --accent: #4fd6be; --accent2: #82aaff;
    --warn: #ffc777;
    --mono: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
    --sans: "Segoe UI", system-ui, -apple-system, sans-serif;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{ background: var(--bg); color: var(--text); font-family: var(--sans); line-height: 1.7; }}
  a {{ color: var(--accent2); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  nav {{
    position: sticky; top: 0; z-index: 50; display: flex; align-items: center; gap: 1.5rem;
    padding: 0.8rem 2rem; background: rgba(11,14,20,0.92); backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--border); font-family: var(--mono); font-size: 0.85rem;
  }}
  nav .logo {{ font-weight: 700; color: var(--accent); margin-right: auto; white-space: nowrap; }}
  nav .logo span {{ color: var(--text); }}
  nav a {{ color: var(--muted); }}
  nav a:hover {{ color: var(--text); text-decoration: none; }}
  .wrap {{ max-width: 860px; margin: 0 auto; padding: 2.5rem 1.5rem 4rem; }}
  .crumb {{ font-family: var(--mono); font-size: 0.8rem; color: var(--muted); margin-bottom: 1.5rem; }}
  h1 {{ font-size: clamp(1.8rem, 5vw, 2.6rem); line-height: 1.2; margin-bottom: 0.4rem; }}
  h1 .pnum {{ color: var(--accent); font-family: var(--mono); }}
  .tagline {{ color: var(--muted); font-size: 1.05rem; margin-bottom: 2rem; }}
  .toc {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1.2rem 1.5rem; margin-bottom: 2.5rem; }}
  .toc .toc-title {{ font-family: var(--mono); font-size: 0.8rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 0.6rem; }}
  .toc a {{ display: block; padding: 0.15rem 0; font-size: 0.92rem; }}
  .toc a .lnum {{ font-family: var(--mono); color: var(--muted); margin-right: 0.5rem; font-size: 0.8rem; }}
  article h2 {{ font-size: 1.5rem; margin: 3rem 0 1rem; padding-top: 1.5rem; border-top: 1px solid var(--border); scroll-margin-top: 70px; }}
  article h2 .lnum {{ font-family: var(--mono); color: var(--accent); font-size: 1.1rem; }}
  article h3 {{ font-size: 1.05rem; margin: 1.6rem 0 0.5rem; color: var(--warn); font-family: var(--mono); }}
  article p {{ margin: 0.8rem 0; }}
  article blockquote {{ border-left: 3px solid var(--accent); padding: 0.4rem 1rem; margin: 1rem 0; color: var(--muted); background: var(--bg-alt); border-radius: 0 8px 8px 0; }}
  article ul, article ol {{ margin: 0.8rem 0 0.8rem 1.5rem; }}
  article li {{ margin: 0.3rem 0; }}
  article code {{ font-family: var(--mono); font-size: 0.85em; background: var(--bg-alt); border: 1px solid var(--border); border-radius: 4px; padding: 0.1em 0.35em; color: var(--warn); }}
  article pre {{ background: var(--bg-alt); border: 1px solid var(--border); border-radius: 10px; padding: 1rem 1.2rem; overflow-x: auto; margin: 1rem 0; }}
  article pre code {{ background: none; border: none; padding: 0; color: var(--text); font-size: 0.82rem; line-height: 1.5; }}
  article table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.9rem; }}
  article th, article td {{ border: 1px solid var(--border); padding: 0.5rem 0.8rem; text-align: left; }}
  article th {{ background: var(--card); font-family: var(--mono); font-size: 0.8rem; }}
  article tr:nth-child(even) td {{ background: var(--bg-alt); }}
  article hr {{ border: none; border-top: 1px solid var(--border); margin: 2rem 0; }}
  .pager {{ display: flex; justify-content: space-between; gap: 1rem; margin-top: 3.5rem; padding-top: 1.5rem; border-top: 1px solid var(--border); font-family: var(--mono); font-size: 0.88rem; }}
  .pager a {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 0.7rem 1.2rem; }}
  .pager a:hover {{ border-color: var(--accent); text-decoration: none; }}
  .pager .spacer {{ flex: 1; }}
</style>
</head>
<body>
<nav>
  <a class="logo" href="../index.html">sdfs<span>://</span>system-design-from-scratch</a>
  <a href="../index.html#curriculum">Curriculum</a>
  <a href="../index.html#glossary">Glossary</a>
</nav>
<div class="wrap">
  <div class="crumb"><a href="../index.html#curriculum">curriculum</a> / phase {num:02d}</div>
  <h1><span class="pnum">{num:02d}</span> {emoji} {name}</h1>
  <div class="tagline">{tagline}</div>
  <div class="toc">
    <div class="toc-title">Lessons in this phase</div>
    {toc}
  </div>
  <article>
{body}
  </article>
  <div class="pager">
    {prev}
    <span class="spacer"></span>
    {next}
  </div>
</div>
</body>
</html>
"""


def main():
    import json

    data_js = (ROOT / "site" / "data.js").read_text(encoding="utf-8")
    start = data_js.index("[")
    end = data_js.rindex("];") + 1
    raw = data_js[start:end]
    raw = re.sub(r"^\s*//.*$", "", raw, flags=re.M)
    raw = re.sub(r'([{\s,])(id|slug|emoji|name|tagline|lessons):', r'\1"\2":', raw)
    curriculum = json.loads(raw)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for idx, ph in enumerate(curriculum):
        md = (PHASES_DIR / ph["slug"] / "README.md").read_text(encoding="utf-8")
        body = md_to_html(md)
        toc = "\n".join(
            f'<a href="#lesson-{i+1:02d}"><span class="lnum">{i+1:02d}</span>{html.escape(t)}</a>'
            for i, t in enumerate(ph["lessons"])
        )
        prev_ph = curriculum[idx - 1] if idx > 0 else None
        next_ph = curriculum[idx + 1] if idx + 1 < len(curriculum) else None
        prev = (
            f'<a href="{prev_ph["slug"]}.html">← {prev_ph["emoji"]} Phase {prev_ph["id"]:02d}</a>'
            if prev_ph else ""
        )
        nxt = (
            f'<a href="{next_ph["slug"]}.html">Phase {next_ph["id"]:02d} {next_ph["emoji"]} →</a>'
            if next_ph else '<a href="../index.html#curriculum">Back to curriculum ↩</a>'
        )
        page = TEMPLATE.format(
            title=ph["name"], num=ph["id"], emoji=ph["emoji"], name=html.escape(ph["name"]),
            tagline=html.escape(ph["tagline"]), toc=toc, body=body, prev=prev, next=nxt,
        )
        out = OUT_DIR / f'{ph["slug"]}.html'
        out.write_text(page, encoding="utf-8")
        print(f"wrote {out.relative_to(ROOT)} ({len(page):,} chars)")


if __name__ == "__main__":
    main()
