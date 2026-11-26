/* Cloud storage and login (Supabase), shared by index.html and report.html.
 * Needs vendor/supabase.min.js and config.js loaded first.
 *
 * Tables (see supabase/schema.sql):
 *   tickets          one row per price list ticket (code is the key)
 *   transport_items  one row per standard transport item
 *   guide_items      one row per guide price (a guide for a place or attraction)
 *   quotes           one row per saved quote; `data` holds the whole quote as the app builds it
 *   settings         a single row (id 1); `data` holds the settings object
 * The app keeps working with the same objects as before (see DATA_FORMAT.md); this file
 * converts them to and from table rows.
 */
window.Cloud = (function () {
  'use strict';

  const cfg = window.QC_CONFIG || {};
  const configured = !!(cfg.supabaseUrl && cfg.supabaseKey && window.supabase && window.supabase.createClient);
  const sb = configured ? window.supabase.createClient(cfg.supabaseUrl, cfg.supabaseKey, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false, storageKey: 'qc.auth' }
  }) : null;
  let user = null;
  const agentDomain = String(cfg.agentEmailDomain || 'agents.local').toLowerCase();
  // "AG01" -> "ag01@agents.local"; a full email address is used as typed.
  const loginEmail = (s) => (s.includes('@') ? s : s.replace(/\s+/g, '') + '@' + agentDomain).toLowerCase();
  // The agent code shown in the app: "ag01@agents.local" -> "AG01"; other emails are shown as they are.
  const agentOf = (email) => { const e = String(email || '').toLowerCase(); return e.endsWith('@' + agentDomain) ? e.slice(0, -agentDomain.length - 1).toUpperCase() : e; };

  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = (v) => (v == null || v === '' ? 0 : Number(v));

  // ---------- small UI pieces: login screen and messages ----------
  const css = `
  .qc-gate { position: fixed; inset: 0; z-index: 100; display: flex; align-items: center; justify-content: center; padding: 16px;
    background: linear-gradient(160deg, #0d1b2a 0%, #13324a 100%); font-family: var(--font, Inter, system-ui, sans-serif); }
  .qc-gate.hidden { display: none; }
  .qc-gate-card { width: 100%; max-width: 380px; background: #fff; border-radius: 16px; padding: 28px; box-shadow: 0 20px 50px rgba(0,0,0,.35); color: #0d1b2a; }
  .qc-gate-card h1 { font-size: 20px; margin: 0 0 4px; }
  .qc-gate-card p { margin: 0 0 18px; color: #5b6b7b; font-size: 13.5px; line-height: 1.5; }
  .qc-gate-card label { display: block; font-size: 13px; font-weight: 600; margin-bottom: 12px; }
  .qc-gate-card input { display: block; width: 100%; box-sizing: border-box; margin-top: 5px; padding: 10px 12px; font: inherit; font-size: 14px;
    border: 1px solid #cfd8e1; border-radius: 10px; }
  .qc-gate-card button { width: 100%; padding: 11px; font-family: inherit; font-size: 14px; font-weight: 600; color: #fff; border: 0; border-radius: 10px; cursor: pointer;
    background: linear-gradient(135deg, #0f9b8e 0%, #0b6f86 100%); }
  .qc-gate-card button:disabled { opacity: .6; cursor: default; }
  .qc-gate-msg { min-height: 1.2em; margin-top: 12px; font-size: 13px; color: #b42318; }
  .qc-gate-msg.info { color: #5b6b7b; }
  .qc-toast { position: fixed; left: 50%; bottom: 20px; transform: translateX(-50%); z-index: 120; max-width: min(560px, calc(100vw - 32px));
    padding: 12px 16px; border-radius: 12px; font: 500 13.5px var(--font, Inter, system-ui, sans-serif); box-shadow: 0 10px 30px rgba(0,0,0,.25);
    background: #b42318; color: #fff; }
  .qc-toast.ok { background: #0b6f86; }
  .qc-toast button { margin-left: 12px; background: transparent; color: inherit; border: 1px solid rgba(255,255,255,.6); border-radius: 8px; padding: 3px 9px; cursor: pointer; font: inherit; }
  `;
  let gate = null;
  function ensureUI() {
    if (gate) return;
    const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    gate = document.createElement('div');
    gate.className = 'qc-gate';
    gate.innerHTML = '<form class="qc-gate-card" novalidate>' +
      '<h1>Quote Calculator</h1><p>Log in with your agent code and password. Everyone in the company shares the same quotes and price list.</p>' +
      '<label>Agent code<input type="text" name="email" autocomplete="username" autocapitalize="characters" spellcheck="false" placeholder="e.g. AG01" required></label>' +
      '<label>Password<input type="password" name="password" autocomplete="current-password" required></label>' +
      '<button type="submit">Log in</button><div class="qc-gate-msg" role="alert"></div></form>';
    document.body.appendChild(gate);
  }
  function gateMsg(text, info) { const m = gate.querySelector('.qc-gate-msg'); m.textContent = text || ''; m.className = 'qc-gate-msg' + (info ? ' info' : ''); }
  function showLoading(text) {
    ensureUI();
    gate.classList.remove('hidden');
    gate.querySelector('.qc-gate-card').innerHTML = '<h1>Quote Calculator</h1><p>' + esc(text) + '</p>';
  }
  function hideGate() { if (gate) gate.classList.add('hidden'); }

  let toastTimer = null;
  function toast(text, kind) {
    ensureUI();
    let t = document.querySelector('.qc-toast');
    if (!t) { t = document.createElement('div'); document.body.appendChild(t); }
    t.className = 'qc-toast' + (kind === 'ok' ? ' ok' : '');
    t.innerHTML = esc(text) + '<button type="button">OK</button>';
    t.querySelector('button').onclick = () => t.remove();
    clearTimeout(toastTimer);
    if (kind === 'ok') toastTimer = setTimeout(() => t.remove(), 4000);
  }

  // Turns a Supabase/network error into a sentence a person can act on.
  function explain(err) {
    const m = (err && (err.message || err.error_description)) || String(err);
    if (/Failed to fetch|NetworkError|Load failed/i.test(m)) return 'No connection to the online database. Check the internet connection and try again.';
    if (/JWT|not authorized|permission denied|row-level security/i.test(m)) return 'You have been logged out. Refresh the page and log in again.';
    return m;
  }
  function fail(what, err) {
    console.error(what, err);
    toast('Could not ' + what + ': ' + explain(err) + ' Refresh the page to see what is saved.');
  }

  // ---------- login ----------
  // Resolves with the signed-in user, showing the login screen first if needed.
  async function requireLogin() {
    ensureUI();
    if (!configured) {
      showLoading('This copy of the app is not connected to a database. Check config.js (see README).');
      return new Promise(() => {});
    }
    const { data } = await sb.auth.getSession();
    if (data && data.session) { user = data.session.user; watchSignOut(); return user; }
    gate.classList.remove('hidden');
    const form = gate.querySelector('form');
    form.email.focus();
    return new Promise((resolve) => {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = form.email.value.trim(), password = form.password.value;
        if (!email || !password) { gateMsg('Enter your agent code and password.'); return; }
        const btn = form.querySelector('button'); btn.disabled = true; gateMsg('Logging in…', true);
        try {
          const { data: d, error } = await sb.auth.signInWithPassword({ email: loginEmail(email), password });
          if (error) throw error;
          user = d.user; gateMsg(''); watchSignOut(); resolve(user);
        } catch (err) {
          const m = err && err.message || '';
          gateMsg(/invalid login credentials/i.test(m) ? 'Wrong agent code or password.' : explain(err));
        } finally { btn.disabled = false; }
      });
    });
  }
  function watchSignOut() {
    sb.auth.onAuthStateChange((event) => { if (event === 'SIGNED_OUT') location.reload(); });
  }
  async function signOut() { await sb.auth.signOut(); location.reload(); }
  async function changePassword(pw) {
    const { error } = await sb.auth.updateUser({ password: pw });
    if (error) throw error;
  }

  // ---------- row conversion ----------
  const ticketToRow = (t) => ({ code: t.code, name: t.name, supplier: t.supplier, adult_price: num(t.adultPrice != null ? t.adultPrice : t.price),
    child_price: num(t.childPrice != null && t.childPrice !== '' ? t.childPrice : (t.adultPrice != null ? t.adultPrice : t.price)),
    valid_until: t.validUntil, confirmed_at: t.confirmedAt || null });
  const rowToTicket = (r) => ({ code: r.code, name: r.name, supplier: r.supplier, adultPrice: Number(r.adult_price), childPrice: Number(r.child_price),
    price: Number(r.adult_price), validUntil: r.valid_until, confirmedAt: r.confirmed_at || '' });
  const transportToRow = (t) => ({ id: t.id, code: t.code || null, name: t.name, supplier: t.supplier, price: num(t.price) });
  const rowToTransport = (r) => ({ id: r.id, code: r.code || '', name: r.name, supplier: r.supplier, price: Number(r.price) });
  const guideToRow = (t) => ({ id: t.id, code: t.code, name: t.name, supplier: t.supplier, price: num(t.price) });
  const rowToGuide = (r) => ({ id: r.id, code: r.code, name: r.name, supplier: r.supplier, price: Number(r.price) });
  const quoteToRow = (q) => ({ id: q.id, quote_number: q.quoteNumber, quote_date: q.date, client_name: q.clientName || '', total: num(q.total), data: q });
  const rowToQuote = (r) => Object.assign({}, r.data, { id: r.id, quoteNumber: r.quote_number });

  // Supabase returns at most 1000 rows per request, so read in pages.
  async function fetchAll(table, order) {
    const out = [], page = 1000;
    for (let from = 0; ; from += page) {
      const { data, error } = await sb.from(table).select('*').order(order).range(from, from + page - 1);
      if (error) throw error;
      out.push(...data);
      if (data.length < page) return out;
    }
  }
  const check = ({ error }) => { if (error) throw error; };
  async function inChunks(list, size, fn) { for (let i = 0; i < list.length; i += size) await fn(list.slice(i, i + size)); }

  // ---------- data ----------
  async function loadQuotes() { return (await fetchAll('quotes', 'id')).map(rowToQuote); }
  async function loadAll() {
    const [tickets, transport, guides, quotes, settingsRows] = await Promise.all([
      fetchAll('tickets', 'code'), fetchAll('transport_items', 'id'), fetchAll('guide_items', 'code'), loadQuotes(),
      sb.from('settings').select('data').eq('id', 1).then((r) => { if (r.error) throw r.error; return r.data; })
    ]);
    return { prices: { tickets: tickets.map(rowToTicket), transport: transport.map(rowToTransport), guides: guides.map(rowToGuide) }, quotes,
      settings: settingsRows.length ? settingsRows[0].data : null };
  }
  async function loadSettings() {
    const r = await sb.from('settings').select('data').eq('id', 1);
    if (r.error) throw r.error;
    return r.data.length ? r.data[0].data : null;
  }
  const upsertTickets = (list) => inChunks(list, 500, async (c) => check(await sb.from('tickets').upsert(c.map(ticketToRow), { onConflict: 'code' })));
  const deleteTicket = async (code) => check(await sb.from('tickets').delete().eq('code', code));
  const upsertTransport = (list) => inChunks(list, 500, async (c) => check(await sb.from('transport_items').upsert(c.map(transportToRow), { onConflict: 'id' })));
  const deleteTransport = async (id) => check(await sb.from('transport_items').delete().eq('id', id));
  const upsertGuides = (list) => inChunks(list, 500, async (c) => check(await sb.from('guide_items').upsert(c.map(guideToRow), { onConflict: 'id' })));
  const deleteGuide = async (id) => check(await sb.from('guide_items').delete().eq('id', id));
  const saveQuote = async (q) => check(await sb.from('quotes').upsert(quoteToRow(q), { onConflict: 'id' }));
  const saveQuotes = (list) => inChunks(list, 100, async (c) => check(await sb.from('quotes').upsert(c.map(quoteToRow), { onConflict: 'id' })));
  const deleteQuote = async (id) => check(await sb.from('quotes').delete().eq('id', id));
  const saveSettings = async (s) => check(await sb.from('settings').upsert({ id: 1, data: s }, { onConflict: 'id' }));

  return {
    configured, requireLogin, signOut, changePassword, showLoading, hideGate, toast, fail, explain,
    get email() { return user ? user.email : ''; },
    get agent() { return user ? agentOf(user.email) : ''; },
    loadAll, loadQuotes, loadSettings, upsertTickets, deleteTicket, upsertTransport, deleteTransport, upsertGuides, deleteGuide,
    saveQuote, saveQuotes, deleteQuote, saveSettings
  };
})();
