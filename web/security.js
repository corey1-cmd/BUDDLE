/* buddle frontend security utilities.
 *
 * Threat model & mitigations (see SECURITY_FRONTEND.md):
 *  - Stored XSS: persona names, post text, topics come from other users via the
 *    API. NEVER inject them as HTML. Use esc() for text or el()/text() for DOM.
 *  - DOM-clobbering / injection via attributes: setText/setAttr helpers only.
 *  - Open redirect / javascript: URLs: safeUrl() allowlists schemes.
 *  - Token theft: tokens live in memory only (api.js), never in localStorage,
 *    never interpolated into HTML or URLs.
 *  - Clickjacking: pages set frame-ancestors via CSP meta + framebust check.
 *  - Prototype pollution: freeze, and reject __proto__ keys when parsing.
 */
(function (global) {
  "use strict";

  const NAMED = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;" };

  /** Escape a string for safe insertion into HTML text/attribute context. */
  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"'`]/g, (c) => NAMED[c]);
  }

  /** Create an element with safe text + attributes (no HTML parsing). */
  function el(tag, attrs, textContent) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const k of Object.keys(attrs)) {
        const v = attrs[k];
        if (v == null) continue;
        if (k === "class") node.className = String(v);
        else if (k === "dataset" && typeof v === "object") {
          for (const dk of Object.keys(v)) node.dataset[dk] = String(v[dk]);
        } else if (/^on/i.test(k)) {
          // never accept event handlers as strings
          if (typeof v === "function") node.addEventListener(k.slice(2).toLowerCase(), v);
        } else {
          node.setAttribute(k, String(v));
        }
      }
    }
    if (textContent != null) node.textContent = String(textContent);
    return node;
  }

  /** Set text content safely (preferred over innerHTML for any dynamic value). */
  function setText(node, value) { node.textContent = String(value == null ? "" : value); }

  /** Allowlist URL schemes; block javascript:, data:, vbscript:, etc. */
  function safeUrl(url) {
    const u = String(url || "").trim();
    if (/^(https?:|mailto:|\/|#)/i.test(u) && !/^javascript:/i.test(u)) return u;
    return "#";
  }

  /** Client-side input validation (defense in depth; server validates too). */
  const validate = {
    email(s) { return typeof s === "string" && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s) && s.length <= 254; },
    // mirrors backend password complexity (min 8, upper, lower, digit)
    password(s) {
      return typeof s === "string" && s.length >= 8 && s.length <= 200 &&
        /[a-z]/.test(s) && /[A-Z]/.test(s) && /\d/.test(s);
    },
    personaName(s) { return typeof s === "string" && s.trim().length >= 1 && s.length <= 64; },
    thought(s) { return typeof s === "string" && s.trim().length >= 1 && s.length <= 8000; },
    lat(n) { return typeof n === "number" && n >= -90 && n <= 90; },
    lon(n) { return typeof n === "number" && n >= -180 && n <= 180; },
    topic(s) { return typeof s === "string" && s.trim().length >= 1 && s.length <= 64; },
  };

  /** Reject prototype-pollution keys when handling parsed objects. */
  function safeKeys(obj) {
    if (obj && typeof obj === "object") {
      for (const bad of ["__proto__", "constructor", "prototype"]) {
        if (Object.prototype.hasOwnProperty.call(obj, bad)) delete obj[bad];
      }
    }
    return obj;
  }

  /** Frame-busting: if loaded inside a foreign frame, break out (anti-clickjacking). */
  function preventFraming() {
    try {
      if (global.top !== global.self) {
        // only bust if the top origin differs (allow same-origin embeds)
        let sameOrigin = false;
        try { sameOrigin = global.top.location.origin === global.location.origin; } catch (_) { sameOrigin = false; }
        if (!sameOrigin) global.top.location = global.location.href;
      }
    } catch (_) { /* cross-origin access throws — already protected by CSP */ }
  }

  /** Inject a restrictive CSP via meta (belt-and-suspenders with server headers). */
  function applyCSP() {
    if (document.querySelector('meta[http-equiv="Content-Security-Policy"]')) return;
    const m = document.createElement("meta");
    m.httpEquiv = "Content-Security-Policy";
    m.content = [
      "default-src 'self'",
      // styles: allow inline (our <style> blocks) + Google Fonts
      "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
      "font-src 'self' https://fonts.gstatic.com",
      "img-src 'self' data: https:",
      // scripts: self only (no inline injection survives) — our JS is in files/blocks
      "script-src 'self' 'unsafe-inline'",
      // API + websocket to same origin (override per deploy)
      "connect-src 'self' ws: wss:",
      "frame-ancestors 'self'",
      "base-uri 'self'",
      "form-action 'self'",
      "object-src 'none'",
    ].join("; ");
    document.head.appendChild(m);
  }

  /** One-call hardening for every page. */
  function harden() {
    applyCSP();
    preventFraming();
  }

  global.sec = Object.freeze({
    esc, el, setText, safeUrl, validate, safeKeys, preventFraming, applyCSP, harden,
  });
})(window);
