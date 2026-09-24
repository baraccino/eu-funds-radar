/* EU Funds Radar — static portal.
   Data is regenerated weekly by GitHub Actions into data/calls.json.
   Your decisions (saved / dismissed) live in this browser only, and can be
   exported to JSON so they survive a device change. */

const LS_KEY = "eufr.decisions.v1";
const state = {
  data: null,
  cats: new Set(),
  q: "",
  sort: "combined",
  showGated: false,
  hideUnknown: false,
  onlySaved: false,
  decisions: load(),
};

function load() {
  try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; }
  catch { return {}; }
}
function save() {
  try { localStorage.setItem(LS_KEY, JSON.stringify(state.decisions)); }
  catch { /* private mode — decisions just won't persist */ }
}

const SCOPE = {
  cantonal: "one canton",
  bih_croats: "Croats in BiH",
  bih_national: "all BiH",
  hr_national: "all Croatia",
  crossborder: "cross-border area",
  cascade: "EU SMEs",
  eu_wide: "all of Europe",
};

const eur = n =>
  n == null ? "—"
  : n >= 1e6 ? "€" + (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M"
  : n >= 1e3 ? "€" + Math.round(n / 1e3) + "k"
  : "€" + Math.round(n);
const num = n => n == null ? "—" : Math.round(n).toLocaleString("en-GB");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------------------------------------------------------------- sorting */
const SORTS = {
  combined: (a, b) =>
    (a.gates_failed.length > 0) - (b.gates_failed.length > 0) ||
    (a.tier ?? 9) - (b.tier ?? 9) ||
    (b.cash_velocity_risk ?? -1) - (a.cash_velocity_risk ?? -1),
  easiest:  (a, b) => (b.easiest_score ?? -1) - (a.easiest_score ?? -1) ||
                      (b.grant_size ?? -1) - (a.grant_size ?? -1),
  cvr:      (a, b) => (b.cash_velocity_risk ?? -1) - (a.cash_velocity_risk ?? -1),
  cv:       (a, b) => (b.cash_velocity ?? -1) - (a.cash_velocity ?? -1),
  weighted: (a, b) => (b.weighted_score ?? -1) - (a.weighted_score ?? -1),
  tier:     (a, b) => (a.tier ?? 9) - (b.tier ?? 9) ||
                      (b.cash_velocity_risk ?? -1) - (a.cash_velocity_risk ?? -1),
  amount:   (a, b) => (b.grant_size ?? -1) - (a.grant_size ?? -1),
  deadline: (a, b) => (a.days_to_deadline ?? 1e6) - (b.days_to_deadline ?? 1e6),
};

const EXPLAIN = {
  combined: "Flagged calls last, then tier (1 = easiest money), then risk-adjusted €/day. The default.",
  easiest: "Most likely to actually land: many awards, few eligible applicants, little work. Built from awards-per-call and how wide the eligibility is — nobody publishes real competition figures, so this is a proxy, not a probability.",
  cvr: "Expected € per day of your effort, discounted for how long the money takes and penalised for long-shot odds.",
  cv: "Expected € per day, risk-neutral. This deliberately favours big grants with low win odds — compare against the risk-adjusted view.",
  weighted: "Classic 0–100 rubric across money, upfront, ease, odds, fit and speed.",
  tier: "Tier 1 = lump sum, paid up front, solo applicant, fast decision. Tier 4 = everything else.",
  amount: "Straight grant size. Ignores how hard or slow it is.",
  deadline: "Soonest deadline first, regardless of value.",
};

/* ---------------------------------------------------------------- filters */
function visible() {
  const q = state.q.toLowerCase().trim();
  return state.data.calls.filter(c => {
    if (!state.showGated && c.gates_failed.length) return false;
    if (state.hideUnknown && c.grant_size == null) return false;
    if (state.onlySaved && state.decisions[c.uid] !== "saved") return false;
    if (state.decisions[c.uid] === "dismissed" && !state.onlySaved) return false;
    if (state.cats.size && !state.cats.has(c.category)) return false;
    if (q) {
      const hay = (c.title + " " + (c.programme || "") + " " +
                   (c.keywords || []).join(" ") + " " + (c.summary || "")).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  }).sort(SORTS[state.sort]);
}

/* ---------------------------------------------------------------- render */
function kpis(rows) {
  const c = state.data.counts;
  const tier1 = rows.filter(r => r.tier === 1).length;
  const saved = Object.values(state.decisions).filter(v => v === "saved").length;
  const soon = rows.filter(r => r.days_to_deadline != null &&
                                r.days_to_deadline >= 0 && r.days_to_deadline <= 30).length;
  const hrbih = rows.filter(r => r.category === "HR→BiH").length;
  const tiles = [
    [rows.length, "shown now"],
    [tier1, "tier 1 — easy money"],
    [hrbih, "Croatian → BiH"],
    [soon, "closing in 30 days"],
    [saved, "you saved"],
  ];
  document.getElementById("kpis").innerHTML = tiles
    .map(([v, l]) => `<div class="kpi"><b>${num(v)}</b><span>${l}</span></div>`).join("");
}

function card(c) {
  const t = c.tier ?? 4;
  const d = c.days_to_deadline;
  const dl = c.deadline
    ? `<span class="${d != null && d <= 30 ? "deadline-soon" : ""}">${c.deadline}${
        d != null ? ` · ${d < 0 ? "closed" : d + "d left"}` : ""}</span>`
    : "no deadline listed";
  const decision = state.decisions[c.uid];

  const headline = state.sort === "easiest"
    ? [c.easiest_score == null ? "—" : c.easiest_score.toFixed(0), "ease / 100"]
    : state.sort === "weighted"
    ? [c.weighted_score == null ? "—" : c.weighted_score.toFixed(0), "score / 100"]
    : state.sort === "amount" || state.sort === "deadline"
      ? [eur(c.grant_size), "grant size"]
      : [c.cash_velocity_risk == null ? "—" : "€" + num(c.cash_velocity_risk), "per effort-day"];

  return `<article class="card t${t} ${c.gates_failed.length ? "gated" : ""} ${decision === "saved" ? "saved" : ""}">
    <div>
      <h3 class="ttl"><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.title)}</a></h3>
      <p class="meta">
        <b>${eur(c.grant_size)}</b>${c.grant_size_assumed && c.grant_size != null ? '<span class="est">est</span>' : ""}
        <span>·</span><span>${esc(c.programme || c.source)}</span>
        <span>·</span><span>${dl}</span>
        <span>·</span><span>${c.effort_days ?? "?"}d effort<span class="est">est</span></span>
        <span>·</span><span>${Math.round((c.upfront_pct ?? 0) * 100)}% up front${c.upfront_assumed ? '<span class="est">est</span>' : ""}</span>
        ${c.scope ? `<span>·</span><span>open to ${esc(SCOPE[c.scope] || c.scope)}${
          c.expected_grants ? ` · ${c.expected_grants} award${c.expected_grants === 1 ? "" : "s"}` : ""}</span>` : ""}
      </p>
      <div class="tags">
        <span class="tag tier">Tier ${t}</span>
        <span class="tag">${esc(c.category)}</span>
        ${c.call_type ? `<span class="tag">${esc(c.call_type)}</span>` : ""}
        ${c.status ? `<span class="tag">${esc(c.status)}</span>` : ""}
        ${c.gates_failed.map(g => `<span class="tag flag">⚠ ${esc(g)}</span>`).join("")}
      </div>
    </div>
    <div class="num">
      <span class="big">${headline[0]}</span>
      <span class="lbl">${headline[1]}</span>
      <div class="acts">
        <button data-act="save" data-uid="${c.uid}">${decision === "saved" ? "★ Saved" : "☆ Save"}</button>
        <button data-act="dismiss" data-uid="${c.uid}">Dismiss</button>
      </div>
    </div>
  </article>`;
}

function sources() {
  const d = state.data;
  const rows = d.sources.map(s => {
    const cls = s.count > 0 ? "ok" : (s.verified ? "bad" : "warn");
    const note = s.count > 0 ? `${s.count} calls`
      : (s.verified ? "0 — selector may have broken" : "0 — unverified source");
    return `<div class="src"><span>${esc(s.name)}</span><span class="${cls}">${note}</span></div>`;
  }).join("");
  const errs = (d.errors || []).length
    ? `<p class="meta" style="color:var(--critical)">⚠ ${d.errors.length} source(s) errored this run: ${
        d.errors.map(e => esc(e.source)).join(", ")}</p>` : "";
  document.getElementById("sources").innerHTML =
    `<h2>Source health</h2>${errs}<div class="srcgrid">${rows}</div>
     <p class="meta" style="margin-top:9px">A source showing 0 is the dangerous case — it looks like a quiet week.
        Run <code>python verify_sources.py</code> to check selectors.</p>`;
}

function render() {
  const rows = visible();
  kpis(rows);
  document.getElementById("explain").textContent = EXPLAIN[state.sort];
  document.getElementById("list").innerHTML = rows.slice(0, 300).map(card).join("");
  document.getElementById("empty").hidden = rows.length > 0;
}

/* ---------------------------------------------------------------- events */
function wire() {
  const cats = [...new Set(state.data.calls.map(c => c.category))].sort();
  document.getElementById("cats").innerHTML = cats
    .map(c => `<button class="chip" aria-pressed="false" data-cat="${esc(c)}">${esc(c)}</button>`).join("");

  document.getElementById("cats").addEventListener("click", e => {
    const b = e.target.closest(".chip"); if (!b) return;
    const c = b.dataset.cat;
    state.cats.has(c) ? state.cats.delete(c) : state.cats.add(c);
    b.setAttribute("aria-pressed", state.cats.has(c));
    render();
  });
  document.getElementById("q").addEventListener("input", e => { state.q = e.target.value; render(); });
  document.getElementById("sort").addEventListener("change", e => { state.sort = e.target.value; render(); });
  for (const [id, key] of [["showGated", "showGated"], ["hideUnknown", "hideUnknown"], ["onlySaved", "onlySaved"]]) {
    document.getElementById(id).addEventListener("change", e => { state[key] = e.target.checked; render(); });
  }
  document.getElementById("list").addEventListener("click", e => {
    const b = e.target.closest("button[data-act]"); if (!b) return;
    const { act, uid } = b.dataset;
    if (act === "save") state.decisions[uid] = state.decisions[uid] === "saved" ? undefined : "saved";
    else state.decisions[uid] = "dismissed";
    if (!state.decisions[uid]) delete state.decisions[uid];
    save(); render();
  });
  // Copy rather than download: the artifact viewer blocks page-initiated
  // saves, so a download link would silently do nothing there.
  document.getElementById("exportBtn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const text = JSON.stringify(state.decisions, null, 2);
    const done = msg => { btn.textContent = msg; setTimeout(() => { btn.textContent = "Copy decisions"; }, 1800); };
    try {
      await navigator.clipboard.writeText(text);
      done("Copied");
    } catch {
      // Clipboard refused (older app views). Show the text so it can be selected.
      const pre = document.getElementById("fallbackExport");
      pre.textContent = text;
      pre.hidden = false;
      pre.scrollIntoView({ behavior: "smooth", block: "center" });
      done("Shown below");
    }
  });
  document.getElementById("themeBtn").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("eufr.theme", next); } catch {}
  });
}

/* ---------------------------------------------------------------- boot */
(async function boot() {
  try { const t = localStorage.getItem("eufr.theme"); if (t) document.documentElement.setAttribute("data-theme", t); } catch {}
  try {
    const r = await fetch("data/calls.json", { cache: "no-cache" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    state.data = await r.json();
  } catch (e) {
    document.getElementById("freshness").textContent = "Could not load data/calls.json — has the scraper run?";
    document.getElementById("list").innerHTML =
      `<p class="empty">No data yet. Run <code>python run.py</code> locally, or wait for Monday's GitHub Action.</p>`;
    return;
  }
  const gen = new Date(state.data.generated);
  const age = Math.floor((Date.now() - gen) / 86400000);
  document.getElementById("freshness").textContent =
    `${num(state.data.counts.total)} calls · refreshed ${gen.toISOString().slice(0, 10)}` +
    (age > 8 ? ` · ⚠ ${age} days old, the weekly job may have stopped` : age ? ` · ${age}d ago` : " · today");
  wire(); sources(); render();
})();
