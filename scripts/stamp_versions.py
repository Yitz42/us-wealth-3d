"""Add a content hash to each data script link in index.html (data/wealth.js?v=1a2b3c4d5e).

GitHub Pages lets browsers cache files for 10 minutes, so right after a push a browser can pair the
new index.html with old data files, and the page breaks. A link that changes whenever its file
changes makes the browser fetch the new file. verify.py runs this last; it can also run on its own.
"""
import hashlib, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    page = ROOT / "index.html"
    html = page.read_text()

    def stamp(m):
        digest = hashlib.sha256((ROOT / "data" / f"{m.group(1)}.js").read_bytes()).hexdigest()[:10]
        return f'<script src="data/{m.group(1)}.js?v={digest}"></script>'

    new, n = re.subn(r'<script src="data/(\w+)\.js(?:\?v=[0-9a-f]+)?"></script>', stamp, html)
    if new != html:
        page.write_text(new)
    print(f"stamped {n} data script links in index.html")


if __name__ == "__main__":
    main()
