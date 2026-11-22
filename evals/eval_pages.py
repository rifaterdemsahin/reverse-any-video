"""Evals for the site: every page has the shared menu, every menu link is a real route, and no page holds a secret.

Run: python -m unittest discover -s evals -p "eval_*.py" -v
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
PAGES = ["landing.html", "start.html", "pricing.html", "setup.html", "settings.html", "account.html", "app.html", "admin-guide.html", "admin-sanity.html", "admin-outputs.html"]
SECRET_PATTERNS = [r"sk_(test|live)_[A-Za-z0-9]{8,}", r"whsec_[A-Za-z0-9]{8,}", r"AKIA[0-9A-Z]{12,}",
                   r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"[0-9a-f]{48}"]


def routes() -> set[str]:
    src = (ROOT / "server.py").read_text()
    found = set(re.findall(r'@app\.(?:get|post)\("([^"]+)"', src))
    return found


def menu_links() -> list[str]:
    js = (DOCS / "menu.js").read_text()
    return re.findall(r'href: "([^"]+)"', js)


class Pages(unittest.TestCase):
    def test_every_page_loads_the_shared_menu(self):
        for name in PAGES:
            text = (DOCS / name).read_text()
            self.assertIn('id="site-menu"', text, name)
            self.assertIn('src="/menu.js"', text, name)

    def test_admin_pages_are_marked_and_customer_pages_are_not(self):
        admin_pages = ["index.html", "setup.html", "settings.html", "admin-guide.html", "admin-sanity.html", "admin-outputs.html"]
        customer_pages = ["landing.html", "start.html", "pricing.html", "account.html"]
        for name in admin_pages:
            self.assertIn('data-area="admin"', (DOCS / name).read_text(), name)
        for name in customer_pages:
            self.assertNotIn('data-area="admin"', (DOCS / name).read_text(), name)

    def test_customer_menu_has_no_admin_links(self):
        customer = re.search(r"var CUSTOMER = \[(.*?)\];", (DOCS / "menu.js").read_text(), re.S).group(1)
        for admin_only in ["/admin", "/settings", "/api/docs", "/healthz"]:
            self.assertNotIn(f'"{admin_only}"', customer, admin_only)

    def test_every_internal_menu_link_is_a_route(self):
        known = routes() | {"/", "/landing", "/api/docs"}   # /api/docs is FastAPI's built-in docs_url
        for link in menu_links():
            if link.startswith("http"):
                continue
            self.assertIn(link, known, f"menu link {link} has no route")

    def test_every_page_has_a_route(self):
        known = routes()
        for route in ["/", "/start", "/pricing", "/account", "/admin", "/admin/setup", "/admin/settings",
                      "/admin/guide", "/admin/sanity", "/admin/outputs", "/admin/login", "/admin/callback", "/admin/logout", "/menu.js"]:
            self.assertIn(route, known, route)

    def test_no_secret_values_in_public_pages(self):
        for path in list(DOCS.glob("*.html")) + [DOCS / "menu.js"]:
            text = path.read_text()
            for pat in SECRET_PATTERNS:
                self.assertIsNone(re.search(pat, text), f"{path.name} matches {pat}")

    def test_dockerfile_copies_every_page_and_module(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        for name in PAGES + ["menu.js", "index.html"]:
            self.assertIn(f"docs/{name}" if name != "app.html" else "docs/index.html", dockerfile, name)
        for module in ["server.py", "reverse_video.py", "reverse_llm.py", "deepinfra.py", "template.py",
                       "pricing.py", "storage.py", "vault.py", "gmail.py", "accounts.py", "payments.py"]:
            self.assertIn(module, dockerfile, module)


if __name__ == "__main__":
    unittest.main()
