const $ = s => document.querySelector(s);
const ROLE_INFO = {
  creator: {label: "Creator", short: "Writes content", blurb: "Write copy, submit it for checking, then revise and resubmit."},
  reviewer: {label: "Reviewer", short: "Approves content", blurb: "Read each draft's findings, then approve it or return it with a comment."},
  admin: {label: "Admin", short: "Manages facts", blurb: "Keep the approved brand facts up to date and watch the insights."}};
// Demo accounts for the prototype only. Remove DEMO and the demo buttons before any real use.
const DEMO = {creator: {u: "creator@trustgate.demo", p: "Creator@123"}, reviewer: {u: "reviewer@trustgate.demo", p: "Reviewer@123"}, admin: {u: "admin@trustgate.demo", p: "Admin@123"}};
const NAV = {creator: ["drafts", "new"], reviewer: ["drafts", "insights", "audit"], admin: ["facts", "drafts", "insights", "audit"]};
const NAMES = {drafts: "Drafts", new: "New draft", insights: "Insights", audit: "Audit trail", facts: "Brand facts"};
const ICONS = {
  drafts: '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/><path d="M10 13h5M10 17h5"/>',
  new: '<path d="M12 5v14M5 12h14"/>',
  insights: '<path d="M5 20V10M12 20V4M19 20v-7"/>',
  audit: '<circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/>',
  facts: '<path d="M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6z"/><path d="M9 12l2 2 4-4"/>'};
const ico = n => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[n]}</svg>`;
const TICK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12l5 5 9-10"/></svg>';
let me = null, role = "creator", pick = "creator", view = "drafts", cur = null, flt = "All", sel = null, curVersion = null;
let newRequestId = null, resubmitRequestId = null;
let factRows = [], factEditId = null, historyFactId = null;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const chip = s => `<span class="chip ${String(s).split(" ")[0].replace(/[^a-zA-Z0-9_-]/g, "")}">${esc(s)}</span>`;
const head = (t, sub, action = "") => `<div class="ph"><div><h1>${t}</h1>${sub ? `<p>${sub}</p>` : ""}</div>${action}</div>`;

async function api(path, o = {}) {
  const r = await fetch("/api" + path, {method: o.method || "GET", body: o.body && JSON.stringify(o.body),
    headers: {"Content-Type": "application/json"}, credentials: "same-origin"});
  let j = {}; try { j = await r.json(); } catch (e) {}
  if (r.status === 401 && !["/login", "/me"].includes(path)) { me = null; renderLogin("Your session has ended. Sign in again."); throw new Error("Your session has ended. Sign in again."); }
  if (!r.ok) { const error = new Error(j.detail || "Something went wrong."); error.status = r.status; throw error; }
  return j;
}
function toast(m) { const t = $("#toast"); t.textContent = m; t.style.display = "block"; clearTimeout(toast.t); toast.t = setTimeout(() => t.style.display = "none", 3800); }
function go(v, id) { view = v; cur = id || null; curVersion = null; sel = null; draw(); window.scrollTo(0, 0); }
async function act(fn) { try { await fn(); } catch (e) { if (e.status === 409 && view === "detail") await draw(); toast(e.message); } }
const requestId = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;

async function draw() {
  $("#nav").innerHTML = NAV[role].map(v => `<button class="${v === view || (view === "detail" && v === "drafts") ? "on" : ""}" onclick="go('${v}')">${ico(v)}<span>${NAMES[v]}</span></button>`).join("");
  $("#me").innerHTML = `<i>${esc(me.name[0])}</i><span><b>${esc(me.name)}</b><small>${ROLE_INFO[role].label}</small></span><button class="signout" onclick="logout()">Sign out</button>`;
  api("/ai/status").then(s => { const b = $("#ai"); b.className = "aibadge" + (s.enabled ? " on" : ""); b.textContent = s.enabled ? "AI review on: " + s.model : "AI review off: rules only"; }).catch(() => {});
  const target = $("#view");
  target.setAttribute("aria-live", "polite"); target.setAttribute("aria-busy", "true");
  target.innerHTML = `<div class="state loading" role="status"><span class="spinner" aria-hidden="true"></span><span>Loading ${esc(NAMES[view] || "view")}...</span></div>`;
  try { target.innerHTML = await V[view](); }
  catch (e) { target.innerHTML = `<section class="state error" role="alert"><h2>Couldn't load this view</h2><p>${esc(e.message)}</p><button class="btn alt" onclick="draw()">Try again</button></section>`; }
  finally { target.setAttribute("aria-busy", "false"); }
}
const fileB64 = f => new Promise(res => { if (!f) return res(""); const r = new FileReader(); r.onload = () => res(r.result.split(",")[1]); r.readAsDataURL(f); });
async function payload(prefix, options = {}) {
  const f = $(prefix + "file").files[0];
  return {title: $(prefix + "title")?.value || "", text: $(prefix + "text").value, filename: f ? f.name : "", file_b64: await fileB64(f), ...options};
}
function hl(t, is) {
  let o = "", p = 0;
  is.map((i, n) => ({...i, n: n + 1})).filter(i => i.end > i.start).sort((a, b) => a.start - b.start).forEach(i => {
    if (i.start < p) return;
    const k = i.classification === "Verified against approved evidence" ? "verified" : i.by === "AI" ? "ai" : i.status === "issue" ? "bad" : "warn";
    o += esc(t.slice(p, i.start)) + `<mark class="${k}" id="m${i.n}" tabindex="0" onclick="pulse(${i.n})" onkeydown="if(event.key==='Enter')pulse(${i.n})">${esc(t.slice(i.start, i.end))}<sup>${i.n}</sup></mark>`;
    p = i.end;
  });
  return o + esc(t.slice(p));
}
function lite(n, on) { $("#m" + n)?.classList.toggle("hot", on); }
function pulse(n) {
  document.querySelectorAll(".hot").forEach(e => e.classList.remove("hot"));
  $("#m" + n)?.classList.add("hot");
  $("#f" + n)?.classList.add("hot");
  $("#f" + n)?.scrollIntoView({block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"});
}
function locateFinding(n) {
  document.querySelectorAll(".hot").forEach(e => e.classList.remove("hot"));
  $("#m" + n)?.classList.add("hot"); $("#f" + n)?.classList.add("hot");
  const mark = $("#m" + n);
  if (mark) { mark.scrollIntoView({block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"}); mark.focus({preventScroll: true}); }
}
function evidenceHtml(issue) {
  const records = issue.evidence || (issue.fact_id ? [issue] : []);
  return records.map(e => `<blockquote class="evidence"><small>Approved evidence · ${esc(e.source_document || issue.source || "Source not recorded")}
    ${e.source_document_id ? `· document #${e.source_document_id}` : ""} · fact #${esc(e.fact_id)} · v${esc(e.fact_version || 1)}</small>
    <b>${esc(e.kind)}: ${esc(e.subject)} = ${esc(e.value)}</b>
    ${e.source_quote ? `<span>${esc(e.source_quote)}</span>` : `<span>No source passage was recorded for this manually entered fact.</span>`}
    ${e.valid_from || e.valid_to ? `<small>Valid ${esc(e.valid_from || "from any date")} to ${esc(e.valid_to || "no end date")}</small>` : ""}
    ${e.fact_id ? `<button type="button" class="btn alt" onclick="showEvidence(${Number(e.fact_id)})">View source and fact history</button>` : ""}</blockquote>`).join("");
}
async function showEvidence(factId) {
  try {
    const result = await api(`/facts/${factId}/evidence`), f = result.fact;
    const history = result.history || [];
    const dlg = document.createElement("dialog");
    dlg.className = "evidence-dialog";
    dlg.innerHTML = `<form method="dialog"><div class="panel-head"><h2>Approved source evidence · fact #${factId}</h2><button class="btn alt">Close</button></div>
      ${f ? `<div class="panel"><b>${esc(f.kind)}: ${esc(f.subject)} = ${esc(f.value)}</b><p>${esc(f.source || "Source not recorded")}</p>${f.source_quote ? `<blockquote class="evidence">${esc(f.source_quote)}</blockquote>` : `<p class="muted">No source passage was recorded.</p>`}<small>Version ${esc(f.version || 1)} · Valid ${esc(f.valid_from || "from any date")} to ${esc(f.valid_to || "no end date")}</small></div>` : `<p class="muted">The current fact was deleted; the historical record remains.</p>`}
      <h3>Fact version history</h3>${history.length ? history.map(h => `<article class="proposal"><b>v${esc(h.version)} · ${esc(h.action)}</b><p>${esc(h.kind)}: ${esc(h.subject)} = ${esc(h.value)}</p><p>${esc(h.source || "Source not recorded")}</p>${h.source_quote ? `<blockquote class="evidence">${esc(h.source_quote)}</blockquote>` : ""}<small>${esc(h.actor)} · ${esc(h.at)}</small></article>`).join("") : `<p class="muted">No historical versions are recorded.</p>`}</form>`;
    document.body.appendChild(dlg); dlg.addEventListener("close", () => dlg.remove(), {once:true}); dlg.showModal();
  } catch (error) { toast(error.message); }
}

function imageReportHtml(version) {
  const checks = version.image_checks || [];
  if (!checks.length) return "";
  const newline = version.content.indexOf("\n");
  const extracted = version.content.startsWith("[Image:") && newline >= 0 ? version.content.slice(newline + 1).trim() : "";
  const results = checks.map(check => `<li class="image-check ${esc(check.status)}"><span class="image-check-status">${esc(check.status.replaceAll("_", " "))}</span>
    <div><b>${esc(check.name)}</b><span>${esc(check.detail)}</span></div></li>`).join("");
  return `<section class="image-report" aria-label="Image checks"><h3>Image checks</h3><p class="muted">Checks include file bounds, sampled palette, and optional near-duplicate comparison against approved whole-image references. This does not reliably verify a logo embedded inside a different poster. TrustGate does not retain submitted draft images; keep the original available for human review.</p>
    <ul>${results}</ul>${extracted ? `<div class="extracted-text"><b>Text returned by vision</b><pre>${esc(extracted)}</pre></div>` : ""}</section>`;
}
function versionDiff(before, after) {
  let start = 0;
  while (start < before.length && start < after.length && before[start] === after[start]) start++;
  let endBefore = before.length, endAfter = after.length;
  while (endBefore > start && endAfter > start && before[endBefore - 1] === after[endAfter - 1]) { endBefore--; endAfter--; }
  return {removed: before.slice(start, endBefore), added: after.slice(start, endAfter)};
}
function donut(parts) {
  const tot = parts.reduce((s, p) => s + p.v, 0);
  if (!tot) return `<p class="muted">No drafts yet.</p>`;
  const R = 52, C = 2 * Math.PI * R; let off = 0;
  const arcs = parts.filter(p => p.v).map(p => { const len = p.v / tot * C; const s = `<circle r="${R}" cx="70" cy="70" fill="none" stroke-width="16" style="stroke:${p.c}" stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-off}" transform="rotate(-90 70 70)"/>`; off += len; return s; }).join("");
  return `<div class="donut"><svg viewBox="0 0 140 140" role="img" aria-label="Drafts by status">${arcs}<text x="70" y="72" text-anchor="middle" class="dn">${tot}</text><text x="70" y="90" text-anchor="middle" class="dl">drafts</text></svg>
    <ul>${parts.map(p => `<li><i style="background:${p.c}"></i>${p.l}: <b>${p.v}</b></li>`).join("")}</ul></div>`;
}
const SAMPLES = {
  wrong: ["Summer sale banner", "SOLARA FLAT 50% OFF. LIFETIME WARRANTY"],
  reworded: ["Weekend promo", "Grab it at half price and enjoy protection for life."],
  clean: ["Launch announcement", "Solara Tech: enjoy 15% off with our 12-month warranty."]};
function fill(k) { $("#n-text").value = SAMPLES[k][1]; if (!$("#n-title").value) $("#n-title").value = SAMPLES[k][0]; }
const STEPS = ["Submitted", "Checked by TrustGate", "Reviewer decision", "Approved by reviewer"];

const V = {
  async drafts() {
    const d = await api("/drafts"), n = s => d.filter(x => x.status === s).length;
    const tabs = [["All", "All", d.length], ["Pending review", "Pending review", n("Pending review")],
      ["Returned", "Returned", n("Returned")], ["Approved by reviewer", "Ready to publish", n("Ready to publish")]];
    const statusLabel = s => s === "Ready to publish" ? "Approved by reviewer" : s;
    const rows = d.filter(x => flt === "All" || x.status === flt);
    const body = rows.length ? `<table><tr><th>Draft</th><th>Version</th><th>Open findings</th><th>Status</th></tr>` + rows.map(x =>
      `<tr class="row2" tabindex="0" onclick="go('detail',${x.id})" onkeydown="if(event.key==='Enter')go('detail',${x.id})"><td><span class="t">${esc(x.title)}</span><span class="s">by ${esc(x.creator)}</span></td><td>v${x.version}</td>
      <td><span class="dot ${x.open_issues ? "has" : ""}">${x.open_issues}</span></td><td>${chip(statusLabel(x.status))}</td></tr>`).join("") + `</table>`
      : `<div class="empty"><b>${d.length ? "Nothing in this view" : "No drafts yet"}</b><p>${d.length ? "Try another status tab." : role === "creator" ? "Check your first piece of content against the approved facts." : "Drafts appear here once a creator submits them."}</p>
      ${role === "creator" && !d.length ? `<button class="btn" onclick="go('new')">Check a draft</button>` : ""}</div>`;
    return head("Drafts", role === "reviewer" ? "Open a draft to read the findings and decide." : "Every piece of content, with its latest check result.",
      role === "creator" ? `<button class="btn" onclick="go('new')">New draft</button>` : "") +
      `<div class="panel flush"><div class="tabs">${tabs.map(([label, value, count]) => `<button class="${flt === value ? "on" : ""}" onclick="flt='${value}';draw()">${label}<b>${count}</b></button>`).join("")}</div>${body}</div>`;
  },
  async new() {
    const ai = (await api("/ai/status")).enabled;
    const list = [["Discounts and offer dates", "Including “half price” and “fifty percent off”"], ["Warranty length", "Including “lifetime” and “warranty for life”"], ["Prices and product names", "Against the approved price list"],
      ["Banned words, tone and risky claims", "“Miracle”, “#1”, “guaranteed”, “cheap”"], ["Posters, banners and PDFs", "Size, brand colours and the words inside the file" + (ai ? "" : " (reading image text needs AI)")]];
    return head("New draft", "Paste copy or upload a file. TrustGate checks it before a reviewer sees it.") + `<div class="two"><div class="panel">
      <div class="samples" aria-label="Try an example"><small class="muted" style="align-self:center">Try an example:</small>
        <button onclick="fill('wrong')">Wrong offer</button><button onclick="fill('reworded')">Reworded claims</button><button onclick="fill('clean')">Clean copy</button></div>
      <label>Title<input id="n-title" placeholder="Summer sale banner"></label>
      <label>Copy to check<textarea id="n-text" placeholder="Solara Tech: Flat 50% off with lifetime warranty!!"></textarea></label>
      <label>Or upload a TXT, DOCX, PDF, PNG or JPG file<input id="n-file" type="file" accept=".txt,.docx,.pdf,.png,.jpg,.jpeg"></label>
      <button class="btn" id="n-submit" onclick="submitNew()">Check draft</button></div>
      <div class="panel"><h2>What TrustGate checks</h2><ul class="checks">${list.map(([a, b]) => `<li>${TICK}<div><b>${a}</b><span>${b}</span></div></li>`).join("")}
        <li class="ai">${TICK}<div><b>Subtler wording and image text (AI)</b><span>${ai ? "Subtler wording, and the text inside images, flagged for a human to review" : "Optional extra layer. Turn it on with an API key to read text inside images and catch subtler wording"}</span></div></li></ul></div></div>`;
  },
  async detail() {
    const d = await api("/drafts/" + cur), lv = d.versions.at(-1), v = d.versions.find(x => x.n === sel) || lv;
    curVersion = lv.n;
    const aiOn = (await api("/ai/status")).enabled, publishStatus = role !== "creator" ? await api("/publishing/status") : {enabled: false}, L = lv.issues;
    const nMismatch = L.filter(i => i.classification === "Mismatch with approved information" || (!i.classification && i.status === "issue")).length;
    const nUnsupported = L.filter(i => i.classification === "Unsupported claim").length;
    const nHuman = L.filter(i => i.classification === "Needs human review" && i.by !== "AI").length;
    const nAI = L.filter(i => i.by === "AI").length;
    const nVerified = L.filter(i => i.classification === "Verified against approved evidence").length;
    const openCount = L.length - nVerified;
    const tally = [nMismatch ? chip(nMismatch + " mismatch") : "", nUnsupported ? chip(nUnsupported + " unsupported") : "",
      nHuman ? chip(nHuman + " needs review") : "", nAI ? chip(nAI + " AI-detected") : "", nVerified ? chip(nVerified + " verified") : ""].join("");
    const reviewRecord = d.review || {};
    const reviewMeta = reviewRecord.reviewer
      ? `${esc(reviewRecord.reviewer)} · ${esc(reviewRecord.reviewed_at)} · version ${esc(reviewRecord.version)} · ${reviewRecord.published ? "Sent to publishing integration; verify publication at destination" : "Not published"}`
      : "Reviewer decision recorded · publication is not performed automatically";
    const statusLabel = d.status === "Ready to publish" ? "Approved by reviewer" : d.status;
    const VD = {"Ready to publish": ["v-ok", "Approved by reviewer", reviewMeta, '<path d="M5 12l5 5 9-10"/>'],
      "Returned": ["v-warn", "Returned by reviewer", reviewMeta, '<path d="M9 7L4 12l5 5M4 12h11a5 5 0 015 5"/>']}[d.status]
      || (openCount ? ["v-bad", `Held: ${openCount} finding${openCount > 1 ? "s" : ""} to review`, "The reviewer decides what happens next.", '<path d="M12 6v7M12 17v.5"/>']
        : ["v-ok", nVerified ? "Claims verified against approved evidence" : "No findings generated", "No finding is not proof of accuracy. A reviewer still makes the final decision.", '<path d="M5 12l5 5 9-10"/>']);
    const st = d.status === "Ready to publish" ? 4 : d.status === "Returned" ? 2 : 2;
    const steps = STEPS.map((s, i) => { const k = d.status === "Ready to publish" ? "done" : i < st ? "done" : i === st ? (d.status === "Returned" ? "stop" : "now") : ""; return `<li class="${k}"><i>${k === "done" ? "✓" : k === "stop" ? "!" : i + 1}</i>${d.status === "Returned" && i === 2 ? "Returned" : s}</li>`; }).join("");
    const imageReport = imageReportHtml(v);
    const priorVersion = d.versions.find(x => x.n === v.n - 1);
    const diff = priorVersion ? versionDiff(priorVersion.content, v.content) : null;
    const diffView = diff ? `<details class="version-diff"><summary>Compare v${v.n} with v${priorVersion.n}</summary><p class="muted">Changed text between the shared beginning and ending of these versions.</p><div class="diff-columns"><div><b>Removed</b><pre>${esc(diff.removed || "No removed text")}</pre></div><div><b>Added</b><pre>${esc(diff.added || "No added text")}</pre></div></div></details>` : "";
    const finds = v.issues.map((i, n) => {
      const classification = i.classification || (i.status === "issue" ? "Mismatch with approved information" : "Needs human review");
      const severity = i.status === "verified" ? "Informational" : i.status === "issue" ? "Action required" : "Review required";
      const tone = classification === "Verified against approved evidence" ? "verified" : classification === "Mismatch with approved information" ? "mismatch" : classification === "Unsupported claim" ? "unsupported" : "review";
      return `<article class="find is-${tone}" id="f${n + 1}" onmouseenter="lite(${n + 1},true)" onmouseleave="lite(${n + 1},false)">
        <header><span class="num">${n + 1}</span><b>${esc(i.type)}</b>${i.by === "AI" ? chip("AI-detected") : ""}</header>
        <div class="finding-tags"><span class="finding-class ${tone}">${esc(classification)}</span><span class="severity">${severity}</span>${i.category ? chip(i.category) : ""}</div>
        <div class="finding-phrase"><small>Exact phrase</small><code>${esc(i.phrase || i.detected)}</code>${i.end > i.start ? `<button type="button" class="btn alt locate" onclick="locateFinding(${n + 1})" aria-label="Locate phrase in draft">Locate in draft</button>` : ""}</div>
        <div class="cmp"><div class="was"><small>Detected</small><span>${esc(i.detected)}</span></div><div class="should"><small>Approved / expected</small><span>${esc(i.approved)}</span></div></div>
        <p class="finding-reason">${esc(i.reason)}</p><p class="src">${i.source && i.source !== "-" ? "Source: " + esc(i.source) : "No approved source on record"}</p>
        ${evidenceHtml(i)}
        ${i.suggestion ? `<div class="fix"><small>Suggested correction</small>${esc(i.suggestion)}</div>` : ""}
        ${role === "reviewer" ? `<div class="finding-feedback"><small>Was this finding correct?</small><button class="${i.feedback?.verdict === "correct" ? "selected" : ""}" onclick="markFinding(${v.id},${n},'correct')">Correct</button><button class="${i.feedback?.verdict === "false_alarm" ? "selected" : ""}" onclick="markFinding(${v.id},${n},'false_alarm')">False alarm</button>${i.feedback ? `<span>Marked by ${esc(i.feedback.reviewer)} · ${esc(i.feedback.verdict.replace("_", " "))}</span>` : ""}</div>` : ""}</article>`;
    }).join("") || `<div class="allclear">${TICK.replace("<svg", '<svg width="22" height="22" style="fill:none;stroke:currentColor;stroke-width:2.4;stroke-linecap:round;stroke-linejoin:round"')}<span>No findings generated for version ${v.n}. This does not guarantee that the copy is accurate; reviewer approval is still required.</span></div>`;
    const cm = d.comments.map(c => `<div class="cm"><b>${esc(c.author)}</b> <small>${c.role} · ${esc(c.at)}</small><br>${esc(c.text)}</div>`).join("");
    const isImg = lv.content.startsWith("[Image:");
    const edit = role === "creator" && d.status === "Returned" ? `<div class="panel"><h2>Revise and resubmit</h2>
      <textarea id="r-text" placeholder="${isImg ? "This draft is an image. Upload the new image below." : ""}">${isImg ? "" : esc(lv.fixed)}</textarea>
      <label>Or upload a new TXT, DOCX, PDF, PNG or JPG file<input id="r-file" type="file" accept=".txt,.docx,.pdf,.png,.jpg,.jpeg"></label>
      <div class="row"><button class="btn" id="resubmit-button" onclick="resubmit()">Resubmit as v${lv.n + 1}</button>${aiOn && !isImg ? `<button class="btn ai" onclick="aiRewrite()">Suggest a rewrite with AI</button>` : ""}</div>
      <p class="muted"><small>The box starts with the suggested fixes applied. Items marked “Needs human review” are left for the reviewer. If you choose a file, the file is checked and the text box is ignored.</small></p></div>` : "";
    const unresolved = L.map((issue, index) => ({issue, index})).filter(({issue}) => issue.classification !== "Verified against approved evidence");
    const unresolvedList = unresolved.length ? `<ul class="decision-findings">${unresolved.map(({issue, index}) => `<li><button type="button" onclick="locateFinding(${index + 1})"><b>${esc(issue.type)}</b><span>${esc(issue.phrase || issue.detected)}</span></button></li>`).join("")}</ul>` : `<p class="muted">No unresolved findings. This is not a guarantee of accuracy.</p>`;
    const rev = role === "reviewer" && d.status === "Pending review" && v.n === lv.n ? `<div class="panel"><h2>Your decision</h2>
      <p>${openCount} unresolved finding${openCount === 1 ? "" : "s"} on version ${lv.n}.</p>${unresolvedList}
      <textarea id="d-comment" style="min-height:80px" placeholder="Comment (required to return, or to approve with open findings)"></textarea>
      <div class="row"><button class="btn yes" id="approve-button" onclick="decide('approve')">Approve (not publish)</button><button class="btn no" id="return-button" onclick="decide('return')">Return to creator</button></div></div>` : "";
    const vt = d.versions.length > 1 ? `<div class="vtabs" role="group" aria-label="Versions">${d.versions.map(x => `<button class="${x.n === v.n ? "on" : ""}" onclick="sel=${x.n};draw()">v${x.n}</button>`).join("")}</div>` : "";
    return head(esc(d.title), `Created by ${esc(d.creator)} · ${chip(statusLabel)}`, `${role !== "creator" && d.status === "Ready to publish" && publishStatus.enabled && !reviewRecord.published ? `<button class="btn yes" onclick="publishDraft(${cur})">Send approved version to publishing integration</button>` : ""}<button class="btn alt" onclick="window.open('/api/drafts/${cur}/report','_blank','noopener')">Review report / Save PDF</button><button class="btn alt" onclick="go('drafts')">Back to drafts</button>`) +
      `<div class="verdict ${VD[0]}"><div class="seal"><svg viewBox="0 0 24 24" aria-hidden="true">${VD[3]}</svg></div><div><b>${VD[1]}</b><span class="sub">${VD[2]}</span></div><div class="tally">${tally}</div></div>
      <ol class="steps" aria-label="Progress">${steps}</ol>
      <div class="detail"><div><div class="panel"><h2>Copy under review</h2>${vt}<p class="meta">Version ${v.n} by ${esc(v.author)}. Select a numbered highlight to jump to its finding.</p>${diffView}${imageReport}<div class="doc">${hl(v.content, v.issues)}</div></div>${edit}</div>
      <div><div class="panel"><h2>Findings (${v.issues.length})</h2>${finds}</div>${rev}
      <div class="panel"><h2>Comments</h2>${cm || `<small class="muted">No comments yet.</small>`}
      ${role !== "admin" ? `<textarea id="c-text" style="min-height:64px;margin-top:10px" placeholder="Add a comment"></textarea><button class="btn alt" onclick="addComment()">Add comment</button>` : ""}</div></div></div>`;
  },
  async facts() {
    const f = await api("/facts"), proposals = await api("/policy-proposals"), aiStatus = await api("/ai/status"), visualAssets = await api("/visual-assets");
    factRows = f;
    const proposalCards = proposals.map(p => `<article class="proposal"><header><b>${chip(p.kind)}</b><span>${esc(p.filename)} · proposal ${p.id}</span></header>
      ${p.matched_fact_id ? `<p class="match-note">Possible match: fact ${p.matched_fact_id} · ${esc(p.matched_subject)} = ${esc(p.matched_value)}</p>` : ""}
      <div class="proposal-fields"><label>Subject<input id="p-${p.id}-subject" value="${esc(p.subject)}"></label><label>Value<input id="p-${p.id}-value" value="${esc(p.value)}"></label>
      <label>Valid from<input id="p-${p.id}-from" type="date" value="${esc(p.valid_from)}"></label><label>Valid to<input id="p-${p.id}-to" type="date" value="${esc(p.valid_to)}"></label>
      <label>Type<select id="p-${p.id}-kind">${["discount", "warranty", "price", "banned"].map(k => `<option ${k === p.kind ? "selected" : ""}>${k}</option>`).join("")}</select></label></div>
      <blockquote class="evidence"><small>Source passage</small>${esc(p.source_quote)}</blockquote>
      <div class="row"><button class="btn alt" onclick="saveProposal(${p.id})">Save edits</button><button class="btn yes" onclick="decideProposal(${p.id},'add')">Approve as new fact</button>
      ${p.matched_fact_id ? `<button class="btn" onclick="decideProposal(${p.id},'update')">Update matched fact</button>` : ""}<button class="btn no" onclick="decideProposal(${p.id},'reject')">Reject</button></div></article>`).join("")
      || `<p class="muted">No pending proposals. Imported policy facts appear here for review.</p>`;
    const history = historyFactId ? await api(`/facts/${historyFactId}/history`) : [];
    const historyPanel = historyFactId ? `<div class="panel"><div class="panel-head"><h2>Fact history · #${historyFactId}</h2><button class="btn alt" onclick="historyFactId=null;draw()">Close</button></div>
      ${history.length ? `<div class="table-scroll"><table><tr><th>Version</th><th>Fact</th><th>Source</th><th>Changed by</th><th>Action</th><th>When</th></tr>${history.map(h => `<tr><td>v${h.version}</td><td>${esc(h.kind)} · ${esc(h.subject)} = ${esc(h.value)}</td><td>${esc(h.source)}${h.source_quote ? `<blockquote class="evidence">${esc(h.source_quote)}</blockquote>` : ""}</td><td>${esc(h.actor)}</td><td>${esc(h.action)}</td><td>${esc(h.at)}</td></tr>`).join("")}</table></div>` : `<p class="muted">No changes recorded yet.</p>`}</div>` : "";
    return head("Brand facts", "Approved facts power every check. Policy imports stay pending until you approve them.") +
      `<div class="panel"><h2>Import a policy</h2><div class="import-row"><label>Policy document<input id="p-file" type="file" accept=".docx,.pdf,.txt"></label>
      ${aiStatus.enabled ? `<label class="inline-check"><input id="p-ai" type="checkbox">Supplement with AI extraction</label>` : `<p class="muted">Deterministic extraction is available. AI extraction is not configured.</p>`}
      <button class="btn" onclick="importPolicy()">Extract draft facts</button></div></div>
      <div class="panel"><h2>Proposed facts (${proposals.length})</h2>${proposalCards}</div>
      <div class="panel"><h2>Approved visual references</h2><p class="muted">Use <b>Logo</b> for a tightly cropped, high-contrast logo image; the checker searches for it inside larger posters at multiple scales. Use <b>Artwork</b> for near-duplicate whole-image screening. Results are review signals, not proof of compliance.</p>
      <div class="import-row"><label>Reference name<input id="va-name" placeholder="Primary logo or approved campaign artwork"></label><label>Reference type<select id="va-type"><option value="logo">Logo (embedded matching)</option><option value="artwork">Artwork (whole-image matching)</option></select></label><label>Reference image<input id="va-file" type="file" accept=".png,.jpg,.jpeg,image/png,image/jpeg"></label><button class="btn" onclick="addVisualAsset()">Add approved reference</button></div>
      ${visualAssets.length ? `<div class="table-scroll"><table><tr><th>Name</th><th>Type</th><th>SHA-256</th><th>Added by</th><th>When</th><th></th></tr>${visualAssets.map(a => `<tr><td>${esc(a.name)}</td><td>${esc(a.asset_type || "artwork")}</td><td><code>${esc(a.sha256.slice(0,16))}…</code></td><td>${esc(a.uploaded_by)}</td><td>${esc(a.created_at)}</td><td><button class="btn no" onclick="removeVisualAsset(${a.id})">Remove</button></td></tr>`).join("")}</table></div>` : `<p class="muted">No visual references added yet.</p>`}</div>
      ${historyPanel}
      <div class="panel"><h2>${factEditId ? `Edit approved fact #${factEditId}` : "Add an approved fact"}</h2><div class="two" style="grid-template-columns:1fr 1fr">
      <div><label>Type<select id="f-kind">${["discount", "warranty", "price", "banned", "term", "tone", "color", "claim"].map(k => `<option ${factEditId && factRows.find(x => x.id === factEditId)?.kind === k ? "selected" : ""}>${k}</option>`).join("")}</select></label>
      <label>Subject<input id="f-subject" value="${esc(factEditId ? factRows.find(x => x.id === factEditId)?.subject : "")}"></label>
      <label>Value<input id="f-value" value="${esc(factEditId ? factRows.find(x => x.id === factEditId)?.value : "")}"></label></div>
      <div><label>Valid from<input id="f-from" type="date" value="${esc(factEditId ? factRows.find(x => x.id === factEditId)?.valid_from : "")}"></label>
      <label>Valid to<input id="f-to" type="date" value="${esc(factEditId ? factRows.find(x => x.id === factEditId)?.valid_to : "")}"></label>
      <label>Source name<input id="f-source" value="${esc(factEditId ? factRows.find(x => x.id === factEditId)?.source : "")}" ${factEditId && factRows.find(x => x.id === factEditId)?.source_document_id ? "disabled" : ""}></label>
      ${factEditId && factRows.find(x => x.id === factEditId)?.source_document_id ? `<p class="muted fact-evidence-note">A manual change to the fact clears its active policy citation. Import and approve a new policy proposal to attach verified evidence.</p>` : ""}
      ${factEditId && factRows.find(x => x.id === factEditId)?.source_quote ? `<blockquote class="evidence"><small>Current approved policy passage</small>${esc(factRows.find(x => x.id === factEditId).source_quote)}</blockquote>` : ""}
      <div class="row"><button class="btn" onclick="saveFact()">${factEditId ? "Save fact version" : "Save fact"}</button>${factEditId ? `<button class="btn alt" onclick="factEditId=null;draw()">Cancel</button>` : ""}</div></div></div></div>
      <div class="panel flush"><table><tr><th>Type</th><th>Subject</th><th>Value</th><th>Valid</th><th>Source / evidence</th><th>Version</th><th></th></tr>` +
      f.map(x => `<tr><td>${chip(x.kind)}</td><td>${esc(x.subject)}</td><td><b>${esc(x.value)}</b></td><td>${esc(x.valid_from)} ${x.valid_to ? "to " + esc(x.valid_to) : ""}</td>
      <td>${esc(x.source)}${x.source_quote ? `<blockquote class="evidence">${esc(x.source_quote)}</blockquote>` : ""}</td><td>v${x.version || 1}</td>
      <td><div class="row"><button class="btn alt" onclick="editFact(${x.id})">Edit</button><button class="btn alt" onclick="showFactHistory(${x.id})">History</button><button class="btn no" onclick="delFact(${x.id})">Remove</button></div></td></tr>`).join("") + `</table></div>`;
  },
  async insights() {
    const a = await api("/analytics"), max = Math.max(1, ...a.by_category.map(x => x.c), ...a.by_source.map(x => x.c));
    const bars = l => `<div class="bars">` + (l.map(x => `<div class="b"><span>${esc(x.name)}</span><span class="track"><span class="fill" style="width:${x.c / max * 100}%"></span></span><b>${x.c}</b></div>`).join("") || `<small class="muted">No findings saved yet.</small>`) + `</div>`;
    const benchmark = a.benchmark, clarity = a.guideline_clarity;
    const claimRow = (name, s, c) => `<tr><td>${name}</td><td><b>${s.precision}%</b></td><td><b>${s.recall}%</b></td><td><b>${s.f1 ?? "n/a"}${s.f1 == null ? "" : "%"}</b></td><td>${c?.accuracy ?? "n/a"}${c ? "%" : ""}</td><td>${s.true_positives}</td><td>${s.false_positives}</td><td>${s.false_negatives}</td></tr>`;
    const draftRow = (name, s) => `<tr><td>${name}</td><td><b>${s.precision}%</b></td><td><b>${s.recall}%</b></td><td><b>${s.f1}%</b></td><td>${s.true_positives}</td><td>${s.false_positives}</td><td>${s.false_negatives}</td><td>${s.true_negatives}</td><td>${s.accuracy}%</td></tr>`;
    const categoryRows = benchmark?.rules?.by_category || [];
    const categoryAi = new Map((benchmark?.rules_ai?.by_category || []).map(x => [x.category, x]));
    const categoryTable = categoryRows.length ? `<div class="table-scroll"><table><tr><th>Issue category</th><th>Rules FP</th><th>Rules FN</th><th>Rules class errors</th>${benchmark?.rules_ai ? "<th>Rules + AI FP</th><th>Rules + AI FN</th><th>Rules + AI class errors</th>" : ""}</tr>${categoryRows.map(x => {
      const aiRow = categoryAi.get(x.category);
      return `<tr><td>${esc(x.category)}</td><td>${x.false_positives}</td><td>${x.false_negatives}</td><td>${x.classification_errors || 0}</td>${benchmark?.rules_ai ? `<td>${aiRow?.false_positives ?? 0}</td><td>${aiRow?.false_negatives ?? 0}</td><td>${aiRow?.classification_errors || 0}</td>` : ""}</tr>`;
    }).join("")}</table></div>` : `<p class="muted">Category breakdown unavailable for this stored benchmark run.</p>`;
    return head("Insights", "Where content goes wrong, and which guidelines need to be clearer.") +
      `<div class="ledger">${[["Drafts reviewed", a.drafts], ["Approved", a.approved], ["Returned", a.returned], ["Awaiting review", a.pending], ["Repeated issues", a.repeated]].map(([k, n], i) => `<div class="${i === 4 && n ? "hl" : ""}"><b>${n}</b><span>${k}</span></div>`).join("")}</div>
      <div class="panel"><div class="panel-head"><div><h2>Measured accuracy</h2><p class="muted">${benchmark ? `Dataset v${esc(benchmark.rules.dataset_version || "unknown")} · ${benchmark.samples} drafts · last run ${esc(benchmark.at)} · AI ${benchmark.ai_enabled ? "evaluated" : "unavailable"}` : "No evaluation run yet. Runs use the frozen fictional dataset and never score live drafts."}</p></div><button class="btn" onclick="runBenchmark()">Run benchmark</button></div>
      ${benchmark ? `<h3>Claim / finding-event detection</h3><div class="table-scroll"><table><tr><th>Checker</th><th>Precision</th><th>Recall</th><th>F1</th><th>Classification accuracy</th><th>True positives</th><th>False positives</th><th>False negatives</th></tr>${claimRow("Rules only", benchmark.rules.claim_level || benchmark.rules, benchmark.rules.classification)}${benchmark.rules_ai ? claimRow("Rules + AI", benchmark.rules_ai.claim_level || benchmark.rules_ai, benchmark.rules_ai.classification) : ""}</table></div>
        ${benchmark.rules.draft_level ? `<h3>Draft-level binary detection</h3><div class="table-scroll"><table><tr><th>Checker</th><th>Precision</th><th>Recall</th><th>F1</th><th>True positives</th><th>False positives</th><th>False negatives</th><th>True negatives</th><th>Accuracy</th></tr>${draftRow("Rules only", benchmark.rules.draft_level)}${benchmark.rules_ai?.draft_level ? draftRow("Rules + AI", benchmark.rules_ai.draft_level) : ""}</table></div>` : ""}
        <h3>False positives, misses and classification errors by issue category</h3>${categoryTable}
        ${benchmark.rules_ai ? "" : `<p class="muted benchmark-note">AI-assisted evaluation unavailable or not run for this configuration. Configure Claude and run again to compare; rules-only metrics remain separate.</p>`}` : `<p class="muted benchmark-note">Precision = TP/(TP+FP), recall = TP/(TP+FN), and F1 is their harmonic mean. Claim-level events require category agreement; draft-level detection measures whether any labelled issue was found.</p>`}</div>
      <div class="two" style="grid-template-columns:1fr 1fr"><div class="panel"><h2>Drafts by status</h2>${donut([{l: "Approved", v: a.approved, c: "var(--ok)"}, {l: "Returned", v: a.returned, c: "#C27A00"}, {l: "Awaiting review", v: a.pending, c: "var(--primary)"}])}</div>
      <div class="panel"><h2>Most common flags</h2>${bars(a.by_category)}</div></div>
      <div class="panel"><h2>Guidelines that trigger the most findings</h2>${bars(a.by_source)}</div>
      <div class="panel"><h2>Guideline clarity</h2>${clarity.length ? `<div class="table-scroll"><table><tr><th>Source / guideline</th><th>Finding</th><th>False alarms</th><th>Reviewer votes</th><th>Dispute rate</th></tr>${clarity.map(x => `<tr><td>${esc(x.name)}</td><td>${esc(x.type)}</td><td>${x.false_alarms}</td><td>${x.votes}</td><td><b>${x.dispute_rate}%</b></td></tr>`).join("")}</table></div>` : `<p class="muted">No finding feedback yet. Reviewer marks will show which guidelines are disputed most often.</p>`}</div>
      <div class="panel"><h2>Questions a manager can answer here</h2><div class="qa"><div><small>Which error repeats most?</small><b>${esc(a.by_category[0]?.name || "No data yet")}</b></div>
      <div><small>Which drafts await approval?</small><b>${a.pending}</b></div><div><small>Which guideline needs clarity?</small><b>${esc(a.by_source[0]?.name || "No data yet")}</b></div></div></div>`;
  },
  async audit() {
    const a = await api("/audit");
    return head("Audit trail", "Who did what, and when. Nothing here can be edited.") + `<div class="panel flush"><table><tr><th>When</th><th>Who</th><th>Action</th><th>Detail</th></tr>` +
      a.map(x => `<tr><td>${esc(x.at)}</td><td>${esc(x.actor)} <small class="muted">${esc(x.role)}</small></td><td class="act">${esc(x.action)}</td><td>${esc(x.detail)}</td></tr>`).join("") + `</table></div>`;
  }
};

const submitNew = () => act(async () => {
  const button = $("#n-submit"); if (!button || button.disabled) return;
  button.disabled = true;
  try {
    newRequestId ||= requestId(); toast("Checking your draft...");
    const result = await api("/drafts", {method: "POST", body: await payload("#n-", {request_id: newRequestId})});
    newRequestId = null; go("detail", result.id);
  } finally { if (button.isConnected) button.disabled = false; }
});
const resubmit = () => act(async () => {
  const button = $("#resubmit-button"); if (!button || button.disabled) return;
  button.disabled = true;
  try {
    resubmitRequestId ||= requestId(); toast("Checking your new version...");
    const result = await api(`/drafts/${cur}/resubmit`, {method: "POST", body: await payload("#r-", {request_id: resubmitRequestId, expected_version: curVersion})});
    resubmitRequestId = null; sel = null; toast(result.duplicate ? `Version ${result.version} was already submitted.` : `Version ${result.version} submitted for review.`); await draw();
  } finally { if (button.isConnected) button.disabled = false; }
});
const aiRewrite = () => act(async () => { toast("Asking AI for a rewrite..."); const r = await api(`/drafts/${cur}/ai-rewrite`, {method: "POST"}); $("#r-text").value = r.text; toast("AI rewrite added to the box. Review it before you resubmit."); });
const addComment = () => act(async () => { await api(`/drafts/${cur}/comments`, {method: "POST", body: {text: $("#c-text").value}}); draw(); });
const decide = decision => act(async () => {
  const buttons = [$("#approve-button"), $("#return-button")].filter(Boolean);
  if (buttons.some(button => button.disabled)) return;
  buttons.forEach(button => { button.disabled = true; });
  try {
    const result = await api(`/drafts/${cur}/decision`, {method: "POST", body: {decision, comment: $("#d-comment").value, expected_version: curVersion}});
    toast(result.published ? "Published." : result.review_decision === "Approved by reviewer" ? "Approved by reviewer. Not published." : "Returned to creator.");
    await draw();
  } finally { buttons.forEach(button => { if (button.isConnected) button.disabled = false; }); }
});
const markFinding = (version_id, finding_index, verdict) => act(async () => { await api(`/drafts/${cur}/feedback`, {method: "POST", body: {version_id, finding_index, verdict}}); draw(); });
const publishDraft = id => act(async () => {
  if (!confirm("Send this reviewer-approved version to the configured publishing integration? The receiving system controls final publication.")) return;
  const result = await api(`/drafts/${id}/publish`, {method: "POST", body: {}});
  toast(result.message || "Sent to publishing integration. Confirm publication in the destination.");
  await draw();
});
const runBenchmark = () => act(async () => { toast("Running labelled benchmark..."); await api("/benchmark/run", {method: "POST"}); toast("Benchmark complete."); draw(); });
const factForm = () => ({kind: $("#f-kind").value, subject: $("#f-subject").value, value: $("#f-value").value, valid_from: $("#f-from").value, valid_to: $("#f-to").value, source: $("#f-source").value});
const saveFact = () => act(async () => { await api(factEditId ? `/facts/${factEditId}` : "/facts", {method: factEditId ? "PUT" : "POST", body: factForm()}); factEditId = null; toast("Fact saved."); draw(); });
const editFact = id => { factEditId = id; historyFactId = null; draw(); };
const showFactHistory = id => { historyFactId = id; factEditId = null; draw(); };
const saveProposal = id => act(async () => { await api(`/policy-proposals/${id}`, {method: "PUT", body: {kind: $("#p-" + id + "-kind").value, subject: $("#p-" + id + "-subject").value, value: $("#p-" + id + "-value").value, valid_from: $("#p-" + id + "-from").value, valid_to: $("#p-" + id + "-to").value}}); toast("Proposal updated."); draw(); });
const decideProposal = (id, decision) => act(async () => { await api(`/policy-proposals/${id}/decision`, {method: "POST", body: {decision}}); toast(decision === "reject" ? "Proposal rejected." : "Fact approved."); draw(); });
const importPolicy = () => act(async () => { const f = $("#p-file").files[0]; if (!f) throw new Error("Choose a DOCX, PDF or TXT policy first."); const result = await api("/policies/import", {method: "POST", body: {filename: f.name, file_b64: await fileB64(f), include_ai: $("#p-ai")?.checked || false}}); toast(result.ai === "failed" ? `${result.proposals} drafts extracted; AI suggestions failed.` : `${result.proposals} draft facts extracted.`); draw(); });
const delFact = id => act(async () => { await api("/facts/" + id, {method: "DELETE"}); draw(); });
const addVisualAsset = () => act(async () => {
  const f = $("#va-file").files[0], name = $("#va-name").value.trim();
  if (!f) throw new Error("Choose a PNG or JPG reference image first.");
  if (!name) throw new Error("Give the reference a descriptive name.");
  await api("/visual-assets", {method: "POST", body: {name, filename: f.name, file_b64: await fileB64(f), asset_type: $("#va-type").value}});
  toast("Approved visual reference added."); draw();
});
const removeVisualAsset = id => act(async () => { await api("/visual-assets/" + id, {method: "DELETE"}); toast("Visual reference removed."); draw(); });

const ILLUS = `<svg class="il" viewBox="0 0 560 380" role="img" aria-label="A web page advert with a wrong 50% offer and a lifetime warranty claim flagged by TrustGate, next to cards showing the approved facts">
  <defs>
    <pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.2" fill="#fff" opacity=".10"/></pattern>
    <linearGradient id="scan" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F5B301" stop-opacity="0"/><stop offset=".85" stop-color="#F5B301" stop-opacity=".45"/><stop offset="1" stop-color="#F5B301"/></linearGradient>
    <clipPath id="win"><rect x="20" y="44" width="350" height="270" rx="14"/></clipPath>
    <clipPath id="c1"><rect x="392" y="92" width="150" height="84" rx="12"/></clipPath>
    <clipPath id="c2"><rect x="392" y="190" width="150" height="84" rx="12"/></clipPath>
  </defs>
  <rect width="560" height="380" fill="url(#dots)"/>
  <circle cx="300" cy="190" r="190" fill="none" stroke="#fff" stroke-opacity=".06"/><circle cx="300" cy="190" r="255" fill="none" stroke="#fff" stroke-opacity=".05"/>

  <g><rect x="20" y="8" width="150" height="26" rx="13" fill="#FBE1DD"/><circle cx="36" cy="21" r="4.5" fill="#C93A2A"/><text x="48" y="26" font-size="12.5" font-weight="700" fill="#7C1F14" textLength="112" lengthAdjust="spacingAndGlyphs">Held: 2 findings</text></g>
  <g><rect x="392" y="8" width="150" height="26" rx="13" fill="#fff" fill-opacity=".1" stroke="#fff" stroke-opacity=".28"/><text x="404" y="26" font-size="12" font-weight="600" fill="#E3ECF6" textLength="126" lengthAdjust="spacingAndGlyphs">Reviewer decides</text></g>

  <rect x="20" y="44" width="350" height="270" rx="14" fill="#fff"/>
  <g clip-path="url(#win)">
    <rect x="20" y="44" width="350" height="34" fill="#E9EEF4"/>
    <circle cx="40" cy="61" r="4.5" fill="#F28B82"/><circle cx="55" cy="61" r="4.5" fill="#F5B301"/><circle cx="70" cy="61" r="4.5" fill="#6CCB9A"/>
    <rect x="92" y="51" width="262" height="20" rx="10" fill="#fff" stroke="#D5DCE5"/>
    <g fill="none" stroke="#5B6B7C" stroke-width="1.3"><circle cx="107" cy="61" r="5.2"/><ellipse cx="107" cy="61" rx="2.2" ry="5.2"/><path d="M101.8 61h10.4"/></g>
    <text x="119" y="65" font-size="11" fill="#5B6B7C" textLength="150" lengthAdjust="spacingAndGlyphs">solara.example/summer-sale</text>

    <rect x="36" y="92" width="318" height="128" rx="10" fill="#F3F5F9"/>
    <g fill="#F5B301"><circle cx="318" cy="150" r="22"/></g>
    <g stroke="#F5B301" stroke-width="3" stroke-linecap="round"><path d="M318 118v-6M318 182v6M286 150h-6M350 150h6M295.4 127.4l-4.2-4.2M340.6 172.6l4.2 4.2M295.4 172.6l-4.2 4.2M340.6 127.4l4.2-4.2"/></g>
    <text x="52" y="113" font-size="11" font-weight="800" fill="#0F2540" textLength="50" lengthAdjust="spacingAndGlyphs">SOLARA</text>

    <rect x="47" y="122" width="182" height="38" rx="4" fill="#FBE1DD"/><rect x="47" y="158" width="182" height="2.5" fill="#C93A2A"/>
    <text class="serif" x="52" y="151" font-size="26" font-weight="700" fill="#14212E" textLength="172" lengthAdjust="spacingAndGlyphs">FLAT 50% OFF</text>
    <rect x="47" y="165" width="153" height="22" rx="4" fill="#FBE1DD"/><rect x="47" y="185" width="153" height="2.5" fill="#C93A2A"/>
    <text class="serif" x="51" y="181" font-size="14" font-weight="700" fill="#14212E" textLength="145" lengthAdjust="spacingAndGlyphs">LIFETIME WARRANTY</text>
    <rect x="52" y="196" width="88" height="20" rx="10" fill="#1A56DB"/><text x="96" y="210" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">Shop now</text>

    <g fill="#F3F5F9"><rect x="36" y="232" width="98" height="64" rx="8"/><rect x="146" y="232" width="98" height="64" rx="8"/><rect x="256" y="232" width="98" height="64" rx="8"/></g>
    <g fill="#E1E7EF"><rect x="46" y="241" width="78" height="26" rx="6"/><rect x="156" y="241" width="78" height="26" rx="6"/><rect x="266" y="241" width="78" height="26" rx="6"/></g>
    <g fill="#CBD3DA"><rect x="46" y="276" width="58" height="6" rx="3"/><rect x="156" y="276" width="58" height="6" rx="3"/><rect x="266" y="276" width="58" height="6" rx="3"/></g>
    <g fill="#E1E7EF"><rect x="46" y="286" width="34" height="5" rx="2.5"/><rect x="156" y="286" width="34" height="5" rx="2.5"/><rect x="266" y="286" width="34" height="5" rx="2.5"/></g>
    <path d="M150 201l0 15 4-3.4 3.2 7 2.6-1.2-3.2-6.8 5.2-.4z" fill="#14212E" stroke="#fff" stroke-width="1.2" stroke-linejoin="round"/>
    <g class="scan"><rect x="20" y="78" width="350" height="26" fill="url(#scan)"/></g>
  </g>
  <g class="pop m1"><circle cx="229" cy="122" r="9.5" fill="#C93A2A" stroke="#fff" stroke-width="2"/><text x="229" y="126" text-anchor="middle" font-size="11" font-weight="800" fill="#fff">1</text></g>
  <g class="pop m2"><circle cx="200" cy="165" r="9.5" fill="#C93A2A" stroke="#fff" stroke-width="2"/><text x="200" y="169" text-anchor="middle" font-size="11" font-weight="800" fill="#fff">2</text></g>

  <g class="pop k1"><rect x="392" y="92" width="150" height="84" rx="12" fill="#fff"/><g clip-path="url(#c1)"><rect x="392" y="92" width="5" height="84" fill="#C93A2A"/></g>
    <circle cx="414" cy="113" r="9" fill="#C93A2A"/><text x="414" y="117" text-anchor="middle" font-size="11" font-weight="800" fill="#fff">1</text>
    <text x="430" y="117" font-size="12.5" font-weight="700" fill="#14212E" textLength="104" lengthAdjust="spacingAndGlyphs">Offer mismatch</text>
    <text x="406" y="142" font-size="12.5" font-weight="800"><tspan fill="#C93A2A" text-decoration="line-through">50%</tspan><tspan fill="#5B6B7C"> → </tspan><tspan fill="#0F7B55">15%</tspan></text>
    <text x="408" y="162" font-size="10.5" fill="#5B6B7C" textLength="124" lengthAdjust="spacingAndGlyphs">Source: Promo Policy v2</text></g>
  <g class="pop k2"><rect x="392" y="190" width="150" height="84" rx="12" fill="#fff"/><g clip-path="url(#c2)"><rect x="392" y="190" width="5" height="84" fill="#C93A2A"/></g>
    <circle cx="414" cy="211" r="9" fill="#C93A2A"/><text x="414" y="215" text-anchor="middle" font-size="11" font-weight="800" fill="#fff">2</text>
    <text x="430" y="215" font-size="12.5" font-weight="700" fill="#14212E" textLength="96" lengthAdjust="spacingAndGlyphs">Warranty claim</text>
    <text x="406" y="240" font-size="12.5" font-weight="800"><tspan fill="#C93A2A" text-decoration="line-through">Lifetime</tspan><tspan fill="#5B6B7C"> → </tspan><tspan fill="#0F7B55">1 year</tspan></text>
    <text x="408" y="260" font-size="10.5" fill="#5B6B7C" textLength="124" lengthAdjust="spacingAndGlyphs">Source: Product Warranty</text></g>

  <circle cx="372" cy="310" r="43" fill="#1B3A63" stroke="#0F2540" stroke-width="6"/>
  <g transform="translate(345 283) scale(1.35)"><path d="M6 36V19C6 10 12.5 4 20 4s14 6 14 15v17" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round"/><path d="M13 21l5 5 9-10" fill="none" stroke="#F5B301" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round"/></g>
  <text x="426" y="306" font-size="12.5" font-weight="700" fill="#fff" textLength="116" lengthAdjust="spacingAndGlyphs">Every claim checked</text>
  <text x="426" y="324" font-size="11" fill="#9FB4CC" textLength="112" lengthAdjust="spacingAndGlyphs">against approved facts</text>
</svg>`;

const lgArt = () => `<section class="lg-art">
      <div class="brand"><svg viewBox="0 0 40 40" width="38" height="38" aria-hidden="true"><path d="M6 36V19C6 10 12.5 4 20 4s14 6 14 15v17" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round"/><path d="M13 21l5 5 9-10" fill="none" stroke="#F5B301" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round"/></svg><div><b>TrustGate</b><small>Check before you publish</small></div></div>
      <div><h1>Catch wrong claims before customers do.</h1>
        <p class="lead">TrustGate compares marketing copy with the facts your company has approved, then hands a clear verdict to a human reviewer.</p>
        <div class="lg-illus">${ILLUS}</div></div>
      <div class="lg-foot">Prototype with demo accounts.</div></section>`;

function renderLogin(msg = "") {
  $("#shell").hidden = true; const L = $("#login"); L.hidden = false;
  L.innerHTML = `${lgArt()}
    <section class="lg-form"><form class="lg-card" onsubmit="doLogin(event)" novalidate>
      <h2>Sign in</h2><p class="sub">Choose your role, then enter your account details.</p>
      <div class="roles" role="radiogroup" aria-label="Sign in as">${Object.entries(ROLE_INFO).map(([k, r]) =>
        `<button type="button" role="radio" data-r="${k}" aria-checked="${k === pick}" class="rolecard ${k === pick ? "on" : ""}" onclick="pickRole('${k}')"><i>${r.label[0]}</i><b>${r.label}</b><small>${r.short}</small></button>`).join("")}</div>
      <p id="lg-blurb">${ROLE_INFO[pick].blurb}</p>
      <label>Email or username<input id="lg-user" type="text" autocomplete="username" autocapitalize="none" spellcheck="false" required></label>
      <label>Password<div class="pw"><input id="lg-pass" type="password" autocomplete="current-password" required><button type="button" id="lg-eye" onclick="togglePw()" aria-label="Show password">Show</button></div></label>
      <div id="lg-err" role="alert">${esc(msg)}</div>
      <button class="btn" id="lg-go" type="submit">Sign in as ${ROLE_INFO[pick].label}</button>
      <div class="lg-or">or</div>
      <button class="btn alt" id="lg-demo" type="button" onclick="doLogin(null, true)">Use the demo ${ROLE_INFO[pick].label} account</button>
      <p class="lg-cred" id="lg-cred">Demo email: <b>${DEMO[pick].u}</b><br>Password: <b>${DEMO[pick].p}</b></p>
      <p class="lg-note">New here? <button type="button" class="lg-link" onclick="renderRegister()">Create an account</button></p>
      <p class="lg-note">Your role is checked on the server, so an account can only sign in as its own role.</p></form></section>`;
  $("#lg-user").focus();
}
function pickRole(k) {
  pick = k;
  document.querySelectorAll(".rolecard").forEach(b => { const on = b.dataset.r === k; b.classList.toggle("on", on); b.setAttribute("aria-checked", on); });
  $("#lg-blurb").textContent = ROLE_INFO[k].blurb; $("#lg-go").textContent = "Sign in as " + ROLE_INFO[k].label;
  $("#lg-demo").textContent = "Use the demo " + ROLE_INFO[k].label + " account"; $("#lg-err").textContent = "";
  $("#lg-cred").innerHTML = `Demo email: <b>${DEMO[k].u}</b><br>Password: <b>${DEMO[k].p}</b>`;
}
function togglePw(p = "lg") { const i = $("#" + p + "-pass"), e = $("#" + p + "-eye"), show = i.type === "password"; i.type = show ? "text" : "password"; e.textContent = show ? "Hide" : "Show"; e.setAttribute("aria-label", show ? "Hide password" : "Show password"); }
async function doLogin(e, demo) {
  if (e) e.preventDefault();
  const u = demo ? DEMO[pick].u : $("#lg-user").value.trim(), p = demo ? DEMO[pick].p : $("#lg-pass").value, err = $("#lg-err"), go1 = $("#lg-go");
  if (!u || !p) { err.textContent = "Enter your username and password."; return; }
  err.textContent = ""; go1.disabled = true;
  try { me = await api("/login", {method: "POST", body: {username: u, password: p, role: pick}}); start(); }
  catch (x) { err.textContent = x.message; go1.disabled = false; if (!demo) { $("#lg-pass").value = ""; $("#lg-pass").focus(); } }
}
function renderRegister(msg = "") {
  $("#shell").hidden = true; const L = $("#login"); L.hidden = false;
  L.innerHTML = `${lgArt()}
    <section class="lg-form"><form class="lg-card" onsubmit="doRegister(event)" novalidate>
      <h2>Create your account</h2><p class="sub">Sign up with your email and a password. New accounts start as Creators.</p>
      <label>Full name<input id="rg-name" autocomplete="name" maxlength="40" required></label>
      <label>Email<input id="rg-email" type="email" autocomplete="email" autocapitalize="none" spellcheck="false" required></label>
      <label>Password<div class="pw"><input id="rg-pass" type="password" autocomplete="new-password" required><button type="button" id="rg-eye" onclick="togglePw('rg')" aria-label="Show password">Show</button></div></label>
      <small class="muted" style="display:block;margin:-8px 0 12px">At least 8 characters, with a letter and a number.</small>
      <label>Confirm password<input id="rg-pass2" type="password" autocomplete="new-password" required></label>
      <div id="lg-err" role="alert">${esc(msg)}</div>
      <button class="btn" id="rg-go" type="submit">Create account</button>
      <p class="lg-note">Already have an account? <button type="button" class="lg-link" onclick="renderLogin()">Sign in</button></p></form></section>`;
  $("#rg-name").focus();
}
async function doRegister(e) {
  e.preventDefault();
  const name = $("#rg-name").value.trim(), email = $("#rg-email").value.trim(), pass = $("#rg-pass").value, err = $("#lg-err"), b = $("#rg-go");
  if (!name || !email || !pass) { err.textContent = "Fill in your name, email and password."; return; }
  if (pass !== $("#rg-pass2").value) { err.textContent = "The two passwords do not match."; return; }
  err.textContent = ""; b.disabled = true;
  try { me = await api("/register", {method: "POST", body: {name, email, password: pass}}); start(); toast("Welcome to TrustGate, " + me.name + "."); }
  catch (x) { err.textContent = x.message; b.disabled = false; }
}
function start() { role = me.role; pick = role; view = NAV[role][0]; cur = null; flt = "All"; sel = null; $("#login").hidden = true; $("#shell").hidden = false; draw(); window.scrollTo(0, 0); }
async function logout() { try { await api("/logout", {method: "POST"}); } catch (e) {} me = null; renderLogin(); toast("Signed out."); }
(async () => { try { me = await api("/me"); start(); } catch (e) { renderLogin(); } })();
