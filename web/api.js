/* buddle frontend API client — single source of truth for backend calls.
 *
 * Every field name / route here matches the FastAPI backend exactly (verified
 * against the Pydantic schemas and router paths). Screens import this instead
 * of hand-writing fetch() calls, so the front<->back contract lives in one place.
 *
 * Auth: JWT bearer. Tokens are cached in memory and write-through persisted to
 * sessionStorage (tab-scoped) so page navigation and refresh keep the session.
 * sessionStorage over localStorage on purpose: it dies with the tab, which
 * shrinks the blast radius of any XSS-stolen token and avoids cross-tab leaks.
 * Base URL defaults to same-origin; override with window.BUDDLE_API_BASE.
 */
(function (global) {
  "use strict";

  const BASE = global.BUDDLE_API_BASE || "";
  const TOKEN_KEY = "buddle.auth.v1";
  let accessToken = null;
  let refreshToken = null;

  // Hydrate once per page load. Storage may be unavailable (private mode,
  // blocked) — in that case we silently fall back to memory-only tokens.
  (function hydrate() {
    try {
      const raw = global.sessionStorage && global.sessionStorage.getItem(TOKEN_KEY);
      if (!raw) return;
      const t = JSON.parse(raw);
      if (t && typeof t.a === "string") {
        accessToken = t.a;
        refreshToken = typeof t.r === "string" ? t.r : null;
      }
    } catch (_) { /* memory-only */ }
  })();

  function persistTokens() {
    try {
      if (!global.sessionStorage) return;
      if (accessToken) {
        global.sessionStorage.setItem(TOKEN_KEY, JSON.stringify({ a: accessToken, r: refreshToken }));
      } else {
        global.sessionStorage.removeItem(TOKEN_KEY);
      }
    } catch (_) { /* quota/blocked → memory-only */ }
  }

  function setTokens(access, refresh) {
    accessToken = access || null;
    if (refresh !== undefined) refreshToken = refresh || null;
    persistTokens();
  }
  function clearTokens() { accessToken = null; refreshToken = null; persistTokens(); }

  async function request(method, path, body, { auth = true, retry = true } = {}) {
    const headers = { "Content-Type": "application/json" };
    if (auth && accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
    const res = await fetch(BASE + path, {
      method,
      headers,
      body: body != null ? JSON.stringify(body) : undefined,
    });

    // transparent refresh on 401 (once)
    if (res.status === 401 && auth && retry && refreshToken) {
      const ok = await tryRefresh();
      if (ok) return request(method, path, body, { auth, retry: false });
    }
    if (!res.ok) {
      let detail = res.statusText;
      try { const j = await res.json(); detail = j.message || j.detail || detail; } catch (_) {}
      throw new ApiError(res.status, detail);
    }
    if (res.status === 204) return null;
    const ct = res.headers.get("content-type") || "";
    return ct.includes("application/json") ? res.json() : res.text();
  }

  class ApiError extends Error {
    constructor(status, message) { super(message); this.name = "ApiError"; this.status = status; }
  }

  async function tryRefresh() {
    try {
      const data = await request("POST", "/v1/auth/refresh",
        { refresh_token: refreshToken }, { auth: false, retry: false });
      setTokens(data.access_token, data.refresh_token);
      return true;
    } catch (_) { clearTokens(); return false; }
  }

  /* ── Auth ──────────────────────────────────────────────── */
  const auth = {
    // SignupRequest: { email, password, password_confirm }
    async signup(email, password, passwordConfirm) {
      return request("POST", "/v1/auth/signup",
        { email, password, password_confirm: passwordConfirm }, { auth: false });
    },
    // LoginRequest: { email, password } -> { access_token, refresh_token }
    async login(email, password) {
      const data = await request("POST", "/v1/auth/login",
        { email, password }, { auth: false });
      setTokens(data.access_token, data.refresh_token);
      return data;
    },
    // Revoke the refresh-token family server-side, then drop local tokens.
    // Network failures are ignored: the family still expires naturally.
    async logout() {
      const rt = refreshToken;
      try {
        if (rt && accessToken) {
          await request("POST", "/v1/auth/logout", { refresh_token: rt }, { retry: false });
        }
      } catch (_) { /* best-effort revoke */ }
      clearTokens();
    },
    isAuthed() { return !!accessToken; },
  };

  /* Soft auth gate for screens.
   *  - token present              → resolves true (render live).
   *  - no token + backend up      → redirects to login.html?next=… (resolves true;
   *                                  navigation is already underway).
   *  - no token + backend down    → resolves false (screen keeps offline demo mode).
   * This preserves the "open the file standalone and get a demo" property. */
  async function requireAuth(next) {
    if (accessToken) return true;
    let backendUp = false;
    try {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), 1500);
      const res = await fetch(BASE + "/health", { signal: ctl.signal });
      clearTimeout(timer);
      backendUp = res.ok;
    } catch (_) { backendUp = false; }
    if (backendUp) {
      const target = next || (location.pathname.split("/").pop() + location.search);
      location.replace(`login.html?next=${encodeURIComponent(target)}`);
      return true;
    }
    return false;
  }

  /* ── Users ─────────────────────────────────────────────── */
  const users = {
    me() { return request("GET", "/v1/users/me"); },
    update(patch) { return request("PATCH", "/v1/users/me", patch); },
  };

  /* ── Personas (location merged into create/update) ─────── */
  const personas = {
    list() { return request("GET", "/v1/personas"); },
    quota() { return request("GET", "/v1/personas/quota"); },
    models() { return request("GET", "/v1/persona-models"); },
    get(id) { return request("GET", `/v1/personas/${id}`); },
    // PersonaCreate: { name, model_key, interest_tag_ids[], location_sharing, location_lat, location_lon }
    create({ name, modelKey, interestTagIds = [], locationSharing = false, lat = null, lon = null }) {
      return request("POST", "/v1/personas", {
        name, model_key: modelKey, interest_tag_ids: interestTagIds,
        location_sharing: locationSharing, location_lat: lat, location_lon: lon,
      });
    },
    // PersonaUpdate: any subset of the above + is_active + preferred_language
    update(id, patch) {
      const body = {};
      if (patch.name !== undefined) body.name = patch.name;
      if (patch.modelKey !== undefined) body.model_key = patch.modelKey;
      if (patch.interestTagIds !== undefined) body.interest_tag_ids = patch.interestTagIds;
      if (patch.isActive !== undefined) body.is_active = patch.isActive;
      if (patch.locationSharing !== undefined) body.location_sharing = patch.locationSharing;
      if (patch.lat !== undefined) body.location_lat = patch.lat;
      if (patch.lon !== undefined) body.location_lon = patch.lon;
      return request("PATCH", `/v1/personas/${id}`, body);
    },
    remove(id) { return request("DELETE", `/v1/personas/${id}`); },
  };

  /* ── Posts (compose) ───────────────────────────────────── */
  const posts = {
    // PostCreate: { persona_id, content_raw, visibility: "public"|"private" }
    // NOTE: user posts go to /v1/posts. POST /v1/plaza/posts is the *agent*
    // route (X-Agent-Key auth) — wiring it here returns 401 for users.
    create({ personaId, contentRaw, visibility = "public" }) {
      return request("POST", "/v1/posts", {
        persona_id: personaId, content_raw: contentRaw, visibility,
      });
    },
    get(id) { return request("GET", `/v1/posts/${id}`); },
    like(id) { return request("PUT", `/v1/plaza/posts/${id}/like`); },
    unlike(id) { return request("DELETE", `/v1/plaza/posts/${id}/like`); },
    comments(id) { return request("GET", `/v1/plaza/posts/${id}/comments`); },
    addComment(id, content, kind = "inform") {
      return request("POST", `/v1/plaza/posts/${id}/comments`, { content, kind });
    },
  };

  /* ── Feed / Inbox ──────────────────────────────────────── */
  const feed = {
    list(cursor, tag) {
      const qs = new URLSearchParams();
      if (cursor) qs.set("cursor", cursor);
      if (tag && tag !== "전체") qs.set("tag", tag);
      const q = qs.toString();
      return request("GET", `/v1/feed${q ? `?${q}` : ""}`);
    },
  };
  const inbox = {
    list(cursor) { return request("GET", `/v1/inbox${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`); },
    listFor(personaId, cursor) {
      return request("GET", `/v1/inbox/persona/${personaId}${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`);
    },
    seen(id) { return request("POST", `/v1/inbox/${id}/seen`); },
  };

  /* ── Sessions (chat) ───────────────────────────────────── */
  const sessions = {
    list(personaId) { return request("GET", `/v1/personas/${personaId}/sessions`); },
    create(personaId, title, topic) {
      return request("POST", `/v1/personas/${personaId}/sessions`, { title, topic: topic || null });
    },
    messages(personaId, sessionId, limit = 40) {
      return request("GET", `/v1/personas/${personaId}/sessions/${sessionId}/messages?limit=${limit}`);
    },
    remove(personaId, sessionId) {
      return request("DELETE", `/v1/personas/${personaId}/sessions/${sessionId}`);
    },
  };

  /* ── Knowledge context (chat reference material) ───────── */
  const knowledge = {
    context(personaId, topic, limit = 8) {
      return request("GET", `/v1/personas/${personaId}/context?topic=${encodeURIComponent(topic)}&limit=${limit}`);
    },
    insights(personaId, topic) {
      return request("GET", `/v1/personas/${personaId}/context/insights?topic=${encodeURIComponent(topic)}`);
    },
  };

  /* ── Proximity (nearby matching) ───────────────────────── */
  const tags = {
    list({ q = null, limit = 50 } = {}) {
      const qs = new URLSearchParams();
      if (q) qs.set("q", q);
      qs.set("limit", String(limit));
      return request("GET", `/v1/tags?${qs.toString()}`);
    },
  };

  const proximity = {
    nearby(personaId, limit = 20) {
      return request("GET", `/v1/proximity/personas/${personaId}/nearby?limit=${limit}`);
    },
    setLocation(personaId, { lat, lon, sharing }) {
      return request("PUT", `/v1/proximity/personas/${personaId}/location`,
        { lat, lon, sharing });
    },
  };

  /* ── Dialogue WebSocket (chat live) ────────────────────── */
  function openDialogue(personaId, { onMessage, onOpen, onClose } = {}) {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const wsBase = BASE.replace(/^https?:/, proto) || `${proto}//${location.host}`;
    const ws = new WebSocket(`${wsBase}/v1/ws/dialogue/${personaId}`);
    ws.addEventListener("open", () => {
      // first frame authenticates (WS auth via first message, not query)
      if (accessToken) ws.send(JSON.stringify({ type: "auth", token: accessToken }));
      onOpen && onOpen();
    });
    ws.addEventListener("message", (e) => {
      let msg; try { msg = JSON.parse(e.data); } catch (_) { return; }
      onMessage && onMessage(msg);
    });
    ws.addEventListener("close", () => onClose && onClose());
    return {
      socket: ws,
      // ClientUserMessage: { type:"user_message", content, session_id? }
      send(content, sessionId) {
        ws.send(JSON.stringify({ type: "user_message", content, session_id: sessionId || null }));
      },
      close() { ws.close(); },
    };
  }

  global.buddle = {
    ApiError, setTokens, clearTokens, requireAuth,
    auth, users, personas, tags, posts, feed, inbox, sessions, knowledge, proximity,
    openDialogue,
  };
})(window);
