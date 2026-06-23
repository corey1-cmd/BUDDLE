/* buddle UX micro-helpers — progressive enhancement only.
   Without JS, content is fully visible and nav still works; this just adds
   the calm scroll-reveal and marks the active bottom-nav item. */
(function (global) {
  "use strict";

  /* Scroll-reveal: elements with .bd-reveal fade up as they enter view.
     Respects prefers-reduced-motion (CSS already no-ops the transition). */
  function reveal() {
    var nodes = global.document.querySelectorAll(".bd-reveal");
    if (!nodes.length) return;
    var reduce = global.matchMedia && global.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // If we can't observe, or motion is reduced, leave content visible (default).
    if (reduce || !("IntersectionObserver" in global)) return;
    // Opt into the JS-driven animation: hide now, reveal on scroll-in.
    nodes.forEach(function (n) { n.classList.add("bd-js-reveal"); });
    var io = new global.IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    nodes.forEach(function (n) { io.observe(n); });
  }

  /* Stagger helper: give sequential children a gentle delay before reveal. */
  function stagger(selector, step) {
    var nodes = global.document.querySelectorAll(selector);
    var s = step || 45;
    nodes.forEach(function (n, i) { n.style.transitionDelay = (i * s) + "ms"; });
  }

  function ready(fn) {
    if (global.document.readyState !== "loading") fn();
    else global.document.addEventListener("DOMContentLoaded", fn);
  }

  global.bdux = { reveal: reveal, stagger: stagger, ready: ready };
  ready(reveal);
})(window);
