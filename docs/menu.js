/* Shared site menu. Every page has <div id="site-menu"></div>.
   Customer pages get the customer menu. Pages marked <body data-area="admin"> get the admin menu.
   Change a link here and it changes on every page of that side. */
(function () {
  // Menu groups. Each group has a title and its links. Edit here; every page picks it up.
  var CUSTOMER = [
    { title: "Start", links: [
      { href: "/", label: "🏠 Home" },
      { href: "/start", label: "🔎 Get a price" },
      { href: "/pricing", label: "💷 Pricing" } ] },
    { title: "Account", links: [
      { href: "/account", label: "👤 My account" } ] },
    { title: "About", links: [
      { href: "https://github.com/rifaterdemsahin/reverse-any-video", label: "🐙 Source", ext: true } ] }
  ];
  var ADMIN = [
    { title: "Work", links: [
      { href: "/admin", label: "🎬 Analyzer" },
      { href: "/admin/sanity", label: "🩺 Sanity check" } ] },
    { title: "Guides", links: [
      { href: "/admin/guide", label: "🧭 Admin guide" },
      { href: "/admin/setup", label: "🛠️ Setup guide" },
      { href: "/admin/settings", label: "⚙️ Settings" } ] },
    { title: "Tools", links: [
      { href: "/api/docs", label: "🔌 API docs" },
      { href: "/healthz", label: "💚 Status" },
      { href: "https://github.com/rifaterdemsahin/reverse-any-video/blob/main/todo.md", label: "✅ Todo", ext: true },
      { href: "https://claude.ai/artifact/EJqZnm3wE3EAVvwidFTuFA", label: "📘 Guide (print)", ext: true } ] },
    { title: "Session", links: [
      { href: "/admin/logout", label: "🚪 Sign out" } ] }
  ];

  var CSS =
    ".site-menu{display:flex;flex-wrap:wrap;gap:14px 22px;margin:0 0 18px;max-width:100%;align-items:center}" +
    ".menu-group{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding-right:14px;border-right:1px solid rgba(127,127,127,.3)}" +
    ".menu-group:last-child{border-right:0}" +
    ".menu-title{font:600 12px/1 ui-sans-serif,system-ui,sans-serif;text-transform:uppercase;letter-spacing:.06em;opacity:.6;margin-right:4px}" +
    ".site-menu a{padding:7px 14px;border:1px solid currentColor;border-radius:999px;text-decoration:none;color:inherit;opacity:.8;font:14px/1.2 ui-sans-serif,system-ui,sans-serif}" +
    ".site-menu a:hover,.site-menu a[aria-current=page]{opacity:1;font-weight:600;border-color:#0f6e5c;color:#0f6e5c}" +
    "@media (prefers-color-scheme:dark){.site-menu a[aria-current=page],.site-menu a:hover{border-color:#5fd0b5;color:#5fd0b5}}";

  function here() {
    var p = location.pathname.replace(/\/index\.html$/, "");
    return p.length > 1 ? p.replace(/\/$/, "") : "/";
  }

  function render() {
    var host = document.getElementById("site-menu");
    if (!host) return;
    var admin = !!(document.body && document.body.dataset && document.body.dataset.area === "admin");
    var groups = admin ? ADMIN : CUSTOMER;
    var style = document.createElement("style");
    style.textContent = CSS;
    document.head.appendChild(style);
    var nav = document.createElement("nav");
    nav.className = "site-menu";
    nav.setAttribute("aria-label", admin ? "Admin" : "Site");
    var current = here();
    groups.forEach(function (g) {
      var box = document.createElement("div");
      box.className = "menu-group";
      var title = document.createElement("span");
      title.className = "menu-title";
      title.textContent = g.title;
      box.appendChild(title);
      g.links.forEach(function (l) {
        var a = document.createElement("a");
        a.href = l.href;
        a.textContent = l.label;
        if (l.ext) { a.target = "_blank"; a.rel = "noopener"; }
        if (!l.ext && l.href === current) a.setAttribute("aria-current", "page");
        box.appendChild(a);
      });
      nav.appendChild(box);
    });
    host.replaceWith(nav);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", render);
  else render();
})();
