/* Shared site menu. Every page has <div id="site-menu"></div>. This script fills it, so the links live in one place.
   Add or change a link here and it changes on every page. */
(function () {
  var LINKS = [
    { href: "/landing", label: "🏠 Home" },
    { href: "/start", label: "🔎 Get a price" },
    { href: "/", label: "🎬 Analyzer" },
    { href: "/pricing", label: "💷 Pricing" },
    { href: "/setup", label: "🧭 Setup guide" },
    { href: "/api/docs", label: "🔌 API docs" },
    { href: "/healthz", label: "💚 Status" },
    { href: "https://claude.ai/artifact/EJqZnm3wE3EAVvwidFTuFA", label: "📘 Guide (print)", ext: true },
    { href: "https://github.com/rifaterdemsahin/reverse-any-video", label: "🐙 Source", ext: true },
    { href: "https://github.com/rifaterdemsahin/reverse-any-video/blob/main/todo.md", label: "✅ Todo", ext: true }
  ];

  var CSS =
    ".site-menu{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 18px;max-width:100%}" +
    ".site-menu a{padding:7px 14px;border:1px solid currentColor;border-radius:999px;text-decoration:none;color:inherit;opacity:.8;font:14px/1.2 ui-sans-serif,system-ui,sans-serif}" +
    ".site-menu a:hover,.site-menu a[aria-current=page]{opacity:1;font-weight:600;border-color:#0f6e5c;color:#0f6e5c}" +
    "@media (prefers-color-scheme:dark){.site-menu a[aria-current=page],.site-menu a:hover{border-color:#5fd0b5;color:#5fd0b5}}";

  function here() {
    var p = location.pathname.replace(/\/index\.html$/, "/");
    return p.length > 1 ? p.replace(/\/$/, "") : "/";
  }

  function render() {
    var host = document.getElementById("site-menu");
    if (!host) return;
    var style = document.createElement("style");
    style.textContent = CSS;
    document.head.appendChild(style);
    var nav = document.createElement("nav");
    nav.className = "site-menu";
    nav.setAttribute("aria-label", "Site");
    var current = here();
    LINKS.forEach(function (l) {
      var a = document.createElement("a");
      a.href = l.href;
      a.textContent = l.label;
      if (l.ext) { a.target = "_blank"; a.rel = "noopener"; }
      if (!l.ext && (l.href === current || (l.href === "/" && current === "/index"))) a.setAttribute("aria-current", "page");
      nav.appendChild(a);
    });
    host.replaceWith(nav);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", render);
  else render();
})();
