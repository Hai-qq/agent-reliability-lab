"""Build and audit the self-contained ARL evidence explorer."""

# ruff: noqa: E501

from __future__ import annotations

import json
from typing import Any

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="description" content="Read-only evidence for Agent Reliability Lab runtime, study harness, scenarios, and stateful authorization.">
<title>ARL Evidence Explorer</title>
<style>
:root{--ink:#edf7f3;--muted:#96aaa3;--bg:#06100e;--panel:#0b1916;--panel2:#10231e;--line:#24423a;--mint:#4df0a1;--cyan:#58d5e5;--amber:#ffc861;--red:#ff7c78;--mono:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;--sans:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(circle at 82% -12%,#164335 0,transparent 34%),linear-gradient(180deg,#07120f 0,#06100e 55%,#050c0b 100%);color:var(--ink);font:14px/1.55 var(--sans)}a{color:inherit}button{font:inherit}code{font-family:var(--mono)}
.shell{width:min(1180px,calc(100% - 40px));margin:auto}.topbar{display:flex;align-items:center;justify-content:space-between;padding:24px 0;border-bottom:1px solid var(--line)}.brand{display:flex;align-items:center;gap:12px;font-weight:760;letter-spacing:-.02em}.mark{display:grid;place-items:center;width:34px;height:34px;border:1px solid #39745f;border-radius:10px;background:#0d211b;color:var(--mint);font:800 12px var(--mono)}.topmeta{color:var(--muted);font:11px var(--mono);letter-spacing:.08em;text-transform:uppercase}
.hero{padding:72px 0 46px}.eyebrow{color:var(--mint);font:760 11px var(--mono);letter-spacing:.18em;text-transform:uppercase}.hero h1{max-width:900px;margin:18px 0 18px;font-size:clamp(42px,7vw,82px);line-height:.96;letter-spacing:-.062em}.hero h1 span{color:var(--mint)}.lede{max-width:760px;margin:0;color:#b5c8c1;font-size:clamp(16px,2vw,20px)}.scope{display:flex;flex-wrap:wrap;gap:8px;margin-top:28px}.scope span{border:1px solid var(--line);border-radius:999px;padding:7px 11px;background:rgba(10,25,21,.72);color:#b9ccc5;font:700 10px var(--mono);letter-spacing:.05em;text-transform:uppercase}
.hero-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:44px}.hero-metric{min-height:128px;padding:20px;border:1px solid var(--line);border-radius:16px;background:linear-gradient(145deg,rgba(17,38,32,.96),rgba(9,22,18,.94))}.hero-metric span{display:block;color:var(--muted);font:700 10px var(--mono);letter-spacing:.1em;text-transform:uppercase}.hero-metric strong{display:block;margin-top:14px;font:680 clamp(24px,3vw,38px) var(--mono);letter-spacing:-.05em}.hero-metric small{display:block;margin-top:5px;color:#7f978e}
.section{padding:46px 0}.section-head{display:flex;align-items:end;justify-content:space-between;gap:24px;margin-bottom:24px}.section-head h2{margin:7px 0 0;font-size:clamp(28px,4vw,46px);letter-spacing:-.045em;line-height:1}.section-head p{max-width:520px;margin:0;color:var(--muted)}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}.filter{border:1px solid var(--line);border-radius:999px;background:#0a1714;color:#a9bdb5;padding:8px 13px;cursor:pointer;font:700 11px var(--mono)}.filter:hover,.filter:focus-visible{border-color:#3f7965;color:var(--ink);outline:none}.filter[aria-pressed="true"]{background:var(--mint);border-color:var(--mint);color:#042118}
.timeline{position:relative;display:grid;gap:14px}.timeline:before{content:"";position:absolute;left:25px;top:28px;bottom:28px;width:1px;background:linear-gradient(var(--mint),#255349)}.card{position:relative;margin-left:56px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(150deg,rgba(16,35,30,.98),rgba(8,20,17,.98));overflow:hidden}.card:before{content:"";position:absolute;left:-44px;top:28px;width:17px;height:17px;border:4px solid #07130f;border-radius:50%;background:var(--mint);box-shadow:0 0 0 1px #367760}.card.hidden{display:none}.card-main{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(300px,.85fr);gap:24px;padding:24px}.version{display:inline-flex;align-items:center;gap:8px;color:var(--mint);font:800 11px var(--mono);letter-spacing:.12em;text-transform:uppercase}.category{color:var(--muted)}.card h3{margin:10px 0 4px;font-size:25px;letter-spacing:-.035em}.focus{color:var(--cyan);font:700 12px var(--mono)}.claim{max-width:690px;margin:14px 0 0;color:#bdd0c8;font-size:15px}.gate{align-self:center}.gate-label{display:flex;justify-content:space-between;gap:16px;color:var(--muted);font:700 10px var(--mono);text-transform:uppercase;letter-spacing:.09em}.bar{height:9px;margin:10px 0 8px;border-radius:999px;background:#07110f;overflow:hidden;border:1px solid #1c382f}.bar span{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--mint),var(--cyan))}.gate-note{color:#839b92;font-size:11px}.metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));border-top:1px solid var(--line)}.metric{padding:15px 18px;border-right:1px solid var(--line)}.metric:last-child{border-right:0}.metric span{display:block;color:var(--muted);font:680 9px var(--mono);letter-spacing:.08em;text-transform:uppercase}.metric strong{display:block;margin-top:7px;font:680 17px var(--mono)}
.audit{border-top:1px solid var(--line);padding:0 24px}.audit summary{cursor:pointer;padding:15px 0;color:#a9bdb5;font:700 11px var(--mono);letter-spacing:.05em;list-style:none}.audit summary::-webkit-details-marker{display:none}.audit summary:after{content:"+";float:right;color:var(--mint)}.audit[open] summary:after{content:"−"}.audit-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;padding:0 0 20px}.digest{min-width:0;padding:12px;border:1px solid #1d382f;border-radius:11px;background:#08130f}.digest b{display:block;color:#789087;font:700 9px var(--mono);letter-spacing:.08em;text-transform:uppercase}.digest code{display:block;margin-top:6px;color:#b8ccc4;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.actions{display:flex;gap:9px;align-items:center;margin-top:15px}.action{display:inline-flex;text-decoration:none;border:1px solid #376c5a;border-radius:9px;padding:8px 11px;color:#c7dad2;font:700 10px var(--mono);letter-spacing:.04em}.action:hover,.action:focus-visible{background:#153126;outline:none}.pass{color:var(--mint)}
.integrity-panel{border:1px solid var(--line);border-radius:18px;overflow:hidden;background:rgba(9,22,18,.9)}table{width:100%;border-collapse:collapse}th,td{padding:14px 16px;border-bottom:1px solid var(--line);text-align:left}th{color:var(--muted);background:#0d1e19;font:700 10px var(--mono);letter-spacing:.09em;text-transform:uppercase}td{font:12px var(--mono)}tr:last-child td{border-bottom:0}.status{display:inline-flex;gap:7px;align-items:center;color:var(--mint);font-weight:800}.status:before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor;box-shadow:0 0 12px currentColor}
.boundary{display:grid;grid-template-columns:1.2fr .8fr;gap:14px}.boundary-copy,.boundary-list{border:1px solid var(--line);border-radius:18px;padding:24px;background:#0a1714}.boundary-copy h3{margin:8px 0 10px;font-size:28px;letter-spacing:-.035em}.boundary-copy p{margin:0;color:var(--muted)}.boundary-list ul{margin:0;padding-left:18px;color:#b9ccc5}.boundary-list li+li{margin-top:10px}
footer{display:flex;justify-content:space-between;gap:20px;padding:28px 0 40px;border-top:1px solid var(--line);color:#7f978e;font:10px var(--mono);letter-spacing:.05em;text-transform:uppercase}
@media(max-width:900px){.hero-metrics{grid-template-columns:repeat(2,1fr)}.card-main{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,1fr)}.metric{border-bottom:1px solid var(--line)}.audit-grid{grid-template-columns:1fr}.boundary{grid-template-columns:1fr}.section-head{display:block}.section-head p{margin-top:12px}}
@media(max-width:560px){.shell{width:min(100% - 24px,1180px)}.topmeta{display:none}.hero{padding-top:48px}.hero-metrics{grid-template-columns:1fr 1fr}.hero-metric{min-height:105px;padding:15px}.timeline:before{display:none}.card{margin-left:0}.card:before{display:none}.metrics{grid-template-columns:1fr}.metric{border-right:0}.actions{align-items:stretch;flex-direction:column}.action{justify-content:center}footer{display:block}.footer-right{margin-top:8px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
</style>
</head>
<body>
<div class="shell">
  <nav class="topbar" aria-label="Evidence explorer">
    <div class="brand"><span class="mark">ARL</span><span>Agent Reliability Lab</span></div>
    <div class="topmeta">v0.14 · read-only evidence</div>
  </nav>
  <header class="hero">
    <div class="eyebrow">Runtime evidence, not self-reported completion</div>
    <h1>Reliability you can <span>inspect.</span></h1>
    <p class="lede">A compact offline view of resumable execution, parallel commit fencing, state-aware recovery, and revision-safe authorization. Every number links back to frozen machine-readable evidence.</p>
    <div class="scope"><span>Local only</span><span>Synthetic state</span><span>Digest-only traces</span><span>Zero model calls</span><span>Zero network calls</span></div>
    <section class="hero-metrics" id="hero-metrics" aria-label="Evidence totals"></section>
  </header>

  <main>
    <section class="section" aria-labelledby="progression-title">
      <div class="section-head"><div><div class="eyebrow">Verified progression</div><h2 id="progression-title">Four reliability layers</h2></div><p>Each percentage is the saved gate for that increment, not a cross-version leaderboard. Expand a card to inspect source and trace manifests.</p></div>
      <div class="filters" role="group" aria-label="Filter increments">
        <button class="filter" data-filter="all" aria-pressed="true">All</button>
        <button class="filter" data-filter="harness" aria-pressed="false">Study harness</button>
        <button class="filter" data-filter="runtime" aria-pressed="false">Runtime</button>
        <button class="filter" data-filter="authorization" aria-pressed="false">Authorization</button>
      </div>
      <div class="timeline" id="timeline"></div>
    </section>

    <section class="section" aria-labelledby="integrity-title">
      <div class="section-head"><div><div class="eyebrow">Evidence integrity</div><h2 id="integrity-title">Saved gates rechecked</h2></div><p>The explorer rebuilds hashes from current files, compares formal and repeat outputs, and refuses generation if an input gate fails.</p></div>
      <div class="integrity-panel"><table><thead><tr><th>Gate</th><th>Coverage</th><th>Status</th></tr></thead><tbody id="integrity-rows"></tbody></table></div>
    </section>

    <section class="section boundary" aria-labelledby="boundary-title">
      <div class="boundary-copy"><div class="eyebrow">Hard boundary</div><h3 id="boundary-title">Built for controlled reliability engineering.</h3><p>This page is generated from local deterministic artifacts. It is a read-only index, not a runtime console, benchmark leaderboard, or claim about model capability.</p></div>
      <div class="boundary-list"><ul id="limitations"></ul></div>
    </section>
  </main>

  <footer><span>Agent Reliability Lab · Evidence Explorer</span><span class="footer-right" id="footer-integrity"></span></footer>
</div>
<script id="arl-evidence" type="application/json">__ARL_DATA__</script>
<script>
const DATA=JSON.parse(document.getElementById('arl-evidence').textContent);
const $=id=>document.getElementById(id);
const esc=value=>String(value??'—').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const short=value=>value?`${value.slice(0,14)}…`:'—';
const traceTotal=DATA.increments.reduce((sum,item)=>sum+item.integrity.trace_manifest.file_count,0);
const sourceTotal=DATA.increments.reduce((sum,item)=>sum+item.integrity.source_manifest.file_count,0);
const hero=[['Verified increments',DATA.increments.length,'v0.10 → v0.13'],['Trace parity',traceTotal,'formal = repeat'],['Source files checked',sourceTotal,'manifest-linked'],['External calls',DATA.metadata.external_network_calls,'model calls: 0']];
$('hero-metrics').innerHTML=hero.map(([label,value,note])=>`<article class="hero-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></article>`).join('');
const categoryLabel={harness:'Study harness',runtime:'State runtime',authorization:'Authorization'};
function card(item){
  const percent=Math.round(item.headline_rate*100);
  const metrics=item.metrics.map(metric=>`<div class="metric"><span>${esc(metric.label)}</span><strong>${esc(metric.value)}</strong></div>`).join('');
  const integrity=item.integrity;
  return `<article class="card" data-category="${esc(item.category)}"><div class="card-main"><div><div class="version">${esc(item.version)} <span class="category">/ ${esc(categoryLabel[item.category])}</span></div><h3>${esc(item.title)}</h3><div class="focus">${esc(item.focus)}</div><p class="claim">${esc(item.claim)}</p><div class="actions"><a class="action" href="${esc(item.artifact_href)}">Open summary JSON</a><a class="action" href="${esc(item.docs_href)}">Read contract & limits</a></div></div><div class="gate"><div class="gate-label"><span>Saved headline gate</span><strong>${percent}%</strong></div><div class="bar" aria-label="${percent} percent"><span style="width:${percent}%"></span></div><div class="gate-note">Increment-specific validity gate · <span class="pass">${integrity.passed?'verified':'failed'}</span></div></div></div><div class="metrics">${metrics}</div><details class="audit"><summary>Integrity details</summary><div class="audit-grid"><div class="digest"><b>Summary SHA-256</b><code title="${esc(integrity.summary_sha256)}">${esc(short(integrity.summary_sha256))}</code></div><div class="digest"><b>Source manifest</b><code title="${esc(integrity.source_manifest.sha256)}">${esc(short(integrity.source_manifest.sha256))} · ${integrity.source_manifest.file_count} files</code></div><div class="digest"><b>Trace manifest</b><code title="${esc(integrity.trace_manifest.sha256)}">${esc(short(integrity.trace_manifest.sha256))} · ${integrity.trace_manifest.file_count} files</code></div></div></details></article>`;
}
$('timeline').innerHTML=DATA.increments.map(card).join('');
for(const button of document.querySelectorAll('.filter'))button.addEventListener('click',()=>{const selected=button.dataset.filter;for(const candidate of document.querySelectorAll('.filter'))candidate.setAttribute('aria-pressed',String(candidate===button));for(const card of document.querySelectorAll('.card'))card.classList.toggle('hidden',selected!=='all'&&card.dataset.category!==selected);});
const validity=DATA.validity;
const rows=[['Saved increment validity',`${DATA.increments.length} summaries`,validity.saved_validity.passed],['Frozen source manifests',`${sourceTotal} referenced files`,validity.source_manifests.passed],['Formal / repeat summaries',`${DATA.increments.length} pairs`,validity.formal_repeat_summaries.passed],['Formal / repeat traces',`${validity.formal_repeat_traces.file_count} pairs`,validity.formal_repeat_traces.passed],['Local synthetic boundary','0 model · 0 network',validity.local_synthetic_boundary.passed],['Self-contained viewer','embedded aggregate data',validity.read_only_viewer.passed]];
$('integrity-rows').innerHTML=rows.map(([gate,coverage,passed])=>`<tr><td>${esc(gate)}</td><td>${esc(coverage)}</td><td><span class="status">${passed?'PASS':'FAIL'}</span></td></tr>`).join('');
$('limitations').innerHTML=DATA.limitations.map(item=>`<li>${esc(item)}</li>`).join('');
$('footer-integrity').textContent=`${DATA.metadata.payload_policy} · all gates: ${validity.all_selected_checks_passed?'pass':'fail'}`;
</script>
</body>
</html>
"""


def build_explorer(evidence: dict[str, Any]) -> str:
    serialized = json.dumps(
        evidence,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    return _TEMPLATE.replace("__ARL_DATA__", serialized)


def audit_viewer(document: str) -> dict[str, Any]:
    forbidden = [
        marker
        for marker in (
            "<script src=",
            "fetch(",
            "XMLHttpRequest",
            "WebSocket",
            "EventSource",
            "sendBeacon",
            "http://",
            "https://",
            "<form",
            "contenteditable",
        )
        if marker in document
    ]
    cases = {
        "embedded_evidence": 'id="arl-evidence"' in document,
        "no_external_or_mutating_markers": not forbidden,
        "local_artifact_links": "Open summary JSON" in document,
        "read_only_label": "read-only evidence" in document.lower(),
    }
    return {
        "cases": cases,
        "forbidden_markers": forbidden,
        "passed": all(cases.values()),
    }
