#!/usr/bin/env python3
"""Word version of main.tex for editing (main.docx), built with pandoc from the PDF build's files.

The PDF stays the reference. This script inlines the generated table bodies, replaces citations by the
numbers that BibTeX gave them in main.bbl (elsarticle-num order), uses the PNG copies of the figures and
lets pandoc turn the equations into editable Word equations. Run it after building main.pdf with
--keep-intermediates so that main.bbl exists:

    cd docs/paper && tectonic --keep-intermediates main.tex
    python3 build_docx.py --pandoc /path/to/pandoc --bbl main.bbl
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

PAPER = Path(__file__).resolve().parent


def bbl_items(bbl):
    """Ordered (key, text) of each \\bibitem in a BibTeX .bbl file."""
    body = bbl.split("\\begin{thebibliography}", 1)[1].split("\\end{thebibliography}")[0]
    items = re.split(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}", body)[1:]
    return [(items[i].strip(), items[i+1].strip()) for i in range(0, len(items), 2)]


def clean_bib_text(text):
    text = re.sub(r"\\newblock\s*", "", text)
    text = re.sub(r"\\href\s*\{[^}]*\}\s*\{\\path\{([^}]*)\}\}", r"\1", text)
    text = re.sub(r"\\href\s*\{[^}]*\}\s*\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\path\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\url\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\doi\{([^}]*)\}", r"doi:\1", text)
    text = re.sub(r"\\(?:emph|textit|textbf)\{([^}]*)\}", r"\1", text)
    return " ".join(text.split())


def table_rows(body):
    """Generated table bodies use \\multirow/\\shortstack/\\addlinespace; flatten them for pandoc."""
    body = re.sub(r"\\multirow\{\d+\}\{\*\}\{\\shortstack\[l\]\{(.*?)\\\\ (.*?)\}\}", r"\1 (\2)", body)
    body = body.replace("\\addlinespace", "")
    return body


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pandoc", required=True)
    parser.add_argument("--bbl", default=str(PAPER/"main.bbl"))
    parser.add_argument("--out", default=str(PAPER/"main.docx"))
    a = parser.parse_args()
    tex = (PAPER/"main.tex").read_text()
    items = bbl_items(Path(a.bbl).read_text())
    number = {key: i+1 for i, (key, _) in enumerate(items)}

    def cite(m):
        keys = [k.strip() for k in m.group(1).split(",")]
        return "[" + ", ".join(str(number[k]) for k in keys) + "]"
    tex = re.sub(r"\\tablebody\{([^}]+)\}", lambda m: table_rows((PAPER/m.group(1)).read_text()), tex)
    tex = re.sub(r"\\cite\{([^}]+)\}", cite, tex)
    tex = tex.replace(".pdf}", ".png}")
    tex = re.sub(r"\\begin\{sidewaystable\}", r"\\begin{table}", tex)
    tex = re.sub(r"\\end\{sidewaystable\}", r"\\end{table}", tex)
    tex = re.sub(r"\\resizebox\{\\textwidth\}\{!\}\{%\n", "", tex)
    tex = tex.replace("\\end{tabular}}", "\\end{tabular}")
    tex = tex.replace("\\linenumbers", "")
    # pandoc's math reader rejects some size commands before delimiters; Word sizes delimiters itself.
    for size in ("\\Bigl", "\\Bigr", "\\bigl", "\\bigr", "\\big"):
        tex = tex.replace(size+"\\|", "\\|").replace(size+"[", "[").replace(size+"]", "]") \
                 .replace(size+"(", "(").replace(size+")", ")").replace(size+"/", "/")
    references = "\n\n".join(f"[{i+1}] {clean_bib_text(text)}" for i, (_, text) in enumerate(items))
    tex = tex.replace("\\bibliographystyle{elsarticle-num}\n\\bibliography{refs}",
                      "\\section*{References}\n\n" + references.replace("&", "\\&").replace("\\\\&", "\\&"))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp)/"main_docx.tex"
        src.write_text(tex)
        subprocess.run([a.pandoc, str(src), "-f", "latex", "-t", "docx", "-o", a.out, "--resource-path", str(PAPER),
                        "--number-sections"], check=True, cwd=PAPER)
    print(a.out)


if __name__ == "__main__":
    main()
