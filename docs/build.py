"""Wrap docs/app.html (the published artifact body) into a standalone docs/index.html for GitHub Pages."""
from pathlib import Path

here = Path(__file__).resolve().parent
body = (here / "app.html").read_text(encoding="utf-8")
page = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
        'body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>\n'
        '</head>\n<body data-area="admin">\n' + body + '\n</body>\n</html>\n')
(here / "index.html").write_text(page, encoding="utf-8")
print(f"wrote {here / 'index.html'} ({len(page):,} bytes)")
