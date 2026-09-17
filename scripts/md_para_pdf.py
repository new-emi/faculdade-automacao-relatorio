"""Converte os documentos de docs/ (Markdown) em HTML pronto para impressao.

Uso:
    python scripts/md_para_pdf.py docs/arquivo.md

Gera docs/arquivo.html com estilo de pagina A4. O PDF e produzido imprimindo
esse HTML no navegador (Ctrl+P -> Salvar como PDF) ou via Chrome/Edge headless.
"""

from __future__ import annotations

import sys
from pathlib import Path

import markdown

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body {
  font-family: "Segoe UI", Calibri, Arial, sans-serif;
  font-size: 10.5pt;
  line-height: 1.5;
  color: #1b1b1b;
  max-width: 180mm;
  margin: 0 auto;
}
h1 { font-size: 20pt; margin: 0 0 4mm; border-bottom: 2px solid #1b1b1b; padding-bottom: 2mm; }
h2 { font-size: 14pt; margin: 7mm 0 2mm; border-bottom: 1px solid #c9c9c9; padding-bottom: 1mm; }
h3 { font-size: 11.5pt; margin: 5mm 0 1.5mm; }
p, li { text-align: justify; }
table { border-collapse: collapse; width: 100%; margin: 3mm 0; font-size: 9pt; }
th, td { border: 1px solid #9a9a9a; padding: 1.5mm 2mm; text-align: left; vertical-align: top; }
th { background: #ececec; }
code { font-family: Consolas, "Courier New", monospace; font-size: 9pt; background: #f2f2f2; padding: 0 1px; }
pre { background: #f6f6f6; border: 1px solid #d5d5d5; padding: 2mm; font-size: 9pt; overflow-x: auto; }
blockquote { border-left: 3px solid #c9c9c9; margin-left: 0; padding-left: 3mm; color: #444; }
hr { border: none; border-top: 1px solid #c9c9c9; margin: 5mm 0; }
strong { color: #000; }
"""


def converter(caminho_md: Path) -> Path:
    if not caminho_md.is_file():
        raise SystemExit(f"Arquivo nao encontrado: {caminho_md}")

    corpo = markdown.markdown(
        caminho_md.read_text(encoding="utf-8"),
        extensions=["tables", "sane_lists", "attr_list"],
    )
    html = (
        "<!DOCTYPE html>\n<html lang=\"pt-BR\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        f"<title>{caminho_md.stem}</title>\n"
        f"<style>{CSS}</style>\n</head>\n<body>\n{corpo}\n</body>\n</html>\n"
    )

    caminho_html = caminho_md.with_suffix(".html")
    caminho_html.write_text(html, encoding="utf-8")
    return caminho_html


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    for argumento in sys.argv[1:]:
        destino = converter(Path(argumento))
        print(destino.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
