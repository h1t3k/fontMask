// remap-guard.js — companion to glyphWeave woff2 shards.
// 1. Keeps protected blocks hidden until shards load, so the gamma (DOM)
//    layer is never flashed on a slow or blocked font fetch.
// 2. Replaces the clipboard payload with a clean notice on copy — the shard
//    remap already garbles copies at the DOM level; this is the readable
//    version for humans. Scrapers with JS off still only reach gamma text.
(function () {
  "use strict";
  var NOTICE = document.documentElement.getAttribute("data-gs-notice") ||
    "This text is protected. Reproduction without permission is prohibited.";
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(function () {
      document.documentElement.classList.add("gs-fonts-ready");
    });
    setTimeout(function () {           // failsafe: never hide content forever
      document.documentElement.classList.add("gs-fonts-ready");
    }, 4000);
  } else {
    document.documentElement.classList.add("gs-fonts-ready");
  }
  function onCopy(e) {
    var sel = document.getSelection();
    if (!sel || sel.isCollapsed) return;
    var node = sel.anchorNode;
    while (node && node.nodeType !== 1) node = node.parentNode;
    if (node && node.closest && node.closest(".gs-protect")) {
      e.clipboardData.setData("text/plain", NOTICE);
      e.preventDefault();
    }
  }
  document.addEventListener("copy", onCopy);
  document.addEventListener("cut", onCopy);
})();
