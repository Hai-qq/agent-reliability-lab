"""Build a self-contained read-only HTML viewer from digest-only ARL traces."""

# ruff: noqa: E501

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def _viewer_episode(episode: dict[str, Any], trace_path: Path) -> dict[str, Any]:
    events = [
        json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line
    ]
    evaluation = episode["evaluation"]
    execution = episode["execution"]
    if evaluation["safe_success"]:
        outcome = "safe_success"
    elif execution["failure_code"] == "conflict_precondition_changed":
        outcome = "classified_abort"
    else:
        outcome = "failed"
    return {
        "episode_id": episode["episode_id"],
        "domain": episode["domain"],
        "task_id": episode["task_id"],
        "seed": episode["seed"],
        "runtime": episode["runtime"],
        "condition": episode["condition"],
        "outcome": outcome,
        "task_success": evaluation["task_success"],
        "safe_success": evaluation["safe_success"],
        "failure_code": execution["failure_code"],
        "conflict_count": execution["conflict_count"],
        "conflict_probe_count": execution["conflict_probe_count"],
        "conflict_rebase_count": execution["conflict_rebase_count"],
        "conflict_abort_count": execution["conflict_abort_count"],
        "compensation_attempt_count": execution["compensation_contract_attempt_count"],
        "compensation_success_count": execution["compensation_contract_success_count"],
        "initial_state_hash": episode["initial_state_hash"],
        "final_state_hash": episode["final_state_hash"],
        "trace_sha256": episode["trace_sha256"],
        "events": [
            {
                "event_id": event["event_id"],
                "parent_event_id": event["parent_event_id"],
                "timestamp_logical": event["timestamp_logical"],
                "actor": event["actor"],
                "event_type": event["event_type"],
                "tool_name": event["tool_name"],
                "error_code": event["error_code"],
                "fault_id": event["fault_id"],
                "input_digest": event["input_digest"],
                "output_digest": event["output_digest"],
                "state_hash_before": event["state_hash_before"],
                "state_hash_after": event["state_hash_after"],
            }
            for event in events
        ],
    }


def viewer_data(summary: dict[str, Any], traces_dir: Path) -> dict[str, Any]:
    episodes = [
        _viewer_episode(episode, traces_dir / episode["trace_file"])
        for episode in summary["episodes"]
    ]
    return {
        "metadata": {
            "increment_version": summary["metadata"]["increment_version"],
            "study_id": summary["metadata"]["study_id"],
            "trace_payload_policy": summary["metadata"]["trace_payload_policy"],
            "model_calls": summary["metadata"]["model_calls"],
            "external_network_calls": summary["metadata"]["external_network_calls"],
        },
        "progress": summary["progress"],
        "resume": summary["resume"],
        "aggregate": summary["aggregate"],
        "episodes": episodes,
    }


def build_trace_viewer(summary: dict[str, Any], traces_dir: Path) -> str:
    """Return a deterministic, dependency-free viewer with embedded digest-only data."""
    data = viewer_data(summary, traces_dir)
    serialized = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    title = html.escape(f"ARL Study {data['metadata']['increment_version']} Trace Viewer")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>{title}</title>
<style>
:root {{
  --bg:#07110f;--surface:#0c1916;--surface-2:#11231e;--line:#234139;
  --text:#eefbf4;--muted:#91aa9f;--green:#4df59b;--cyan:#55d9e8;
  --yellow:#f5c95b;--red:#ff7b75;--mono:ui-monospace,SFMono-Regular,Menlo,monospace;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:radial-gradient(circle at 85% -10%,#123e31 0,transparent 36%),var(--bg);color:var(--text);font:14px/1.5 Inter,ui-sans-serif,system-ui,sans-serif}}
header{{padding:34px clamp(20px,5vw,72px) 24px;border-bottom:1px solid var(--line)}}
.eyebrow{{font:700 11px/1 var(--mono);letter-spacing:.18em;text-transform:uppercase;color:var(--green)}}
h1{{margin:12px 0 8px;font-size:clamp(28px,5vw,54px);letter-spacing:-.045em;line-height:1}}
.subtitle{{max-width:850px;color:var(--muted);font-size:15px}}
main{{padding:24px clamp(20px,5vw,72px) 64px}}
.metrics{{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:12px;margin-bottom:20px}}
.metric{{background:linear-gradient(145deg,var(--surface-2),var(--surface));border:1px solid var(--line);border-radius:14px;padding:16px}}
.metric span{{display:block;color:var(--muted);font:700 10px var(--mono);letter-spacing:.11em;text-transform:uppercase}}
.metric strong{{display:block;margin-top:7px;font:650 26px var(--mono)}}
.toolbar{{display:grid;grid-template-columns:minmax(220px,2fr) repeat(4,minmax(135px,1fr));gap:10px;margin:20px 0}}
input,select{{width:100%;border:1px solid var(--line);border-radius:10px;background:#0a1512;color:var(--text);padding:10px 12px;font:12px var(--mono)}}
.panel{{border:1px solid var(--line);border-radius:14px;background:rgba(12,25,22,.92);overflow:hidden}}
.table-wrap{{overflow:auto;max-height:520px}}
table{{width:100%;border-collapse:collapse;min-width:980px}}
th{{position:sticky;top:0;z-index:1;background:#10211c;color:var(--muted);font:700 10px var(--mono);letter-spacing:.09em;text-align:left;text-transform:uppercase}}
th,td{{padding:11px 13px;border-bottom:1px solid #193129;white-space:nowrap}}
tbody tr{{cursor:pointer;transition:background .15s ease}}
tbody tr:hover,tbody tr.active{{background:#142a23}}
code,.mono{{font-family:var(--mono);font-size:11px}}
.pill{{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:999px;padding:3px 8px;font:700 10px var(--mono)}}
.safe_success{{color:var(--green);border-color:#297f55}}.classified_abort{{color:var(--yellow);border-color:#78642c}}.failed{{color:var(--red);border-color:#743d39}}
.detail{{display:none;padding:20px;border-top:1px solid var(--line)}}
.detail.visible{{display:block}}
.detail-head{{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:16px}}
.detail h2{{margin:0;font-size:20px}}
.digest-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:14px 0}}
.digest{{background:#091411;border:1px solid #1c352d;border-radius:10px;padding:10px;overflow:hidden}}
.digest b{{display:block;color:var(--muted);font:700 9px var(--mono);letter-spacing:.08em;text-transform:uppercase}}
.digest code{{display:block;margin-top:5px;overflow:hidden;text-overflow:ellipsis}}
.events{{max-height:480px;overflow:auto;border:1px solid #1c352d;border-radius:10px}}
.event{{display:grid;grid-template-columns:48px 160px 1fr 170px;gap:10px;padding:9px 11px;border-bottom:1px solid #193129;font:11px var(--mono)}}
.event:last-child{{border-bottom:0}}.event .type{{color:var(--cyan)}}.event .error{{color:var(--yellow);overflow:hidden;text-overflow:ellipsis}}
.empty{{padding:48px;text-align:center;color:var(--muted)}}
footer{{margin-top:18px;color:var(--muted);font:11px var(--mono)}}
@media(max-width:900px){{.metrics{{grid-template-columns:repeat(2,1fr)}}.toolbar{{grid-template-columns:1fr 1fr}}.toolbar input{{grid-column:1/-1}}.digest-grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header>
  <div class="eyebrow">Agent Reliability Lab · Read-only evidence</div>
  <h1>Study trace viewer</h1>
  <div class="subtitle">A self-contained view of scheduler progress, recovery outcomes, and append-only digest traces. No API, network request, raw task payload, or mutable control is present.</div>
</header>
<main>
  <section class="metrics" id="metrics"></section>
  <section class="toolbar" aria-label="Trace filters">
    <input id="search" type="search" placeholder="Search episode, task, error…">
    <select id="domain"><option value="">All domains</option></select>
    <select id="runtime"><option value="">All runtimes</option></select>
    <select id="condition"><option value="">All conditions</option></select>
    <select id="outcome"><option value="">All outcomes</option></select>
  </section>
  <section class="panel">
    <div class="table-wrap"><table>
      <thead><tr><th>Episode</th><th>Domain</th><th>Runtime</th><th>Condition</th><th>Outcome</th><th>Failure</th><th>Events</th></tr></thead>
      <tbody id="rows"></tbody>
    </table></div>
    <div id="empty" class="empty" hidden>No episodes match the current filters.</div>
    <div id="detail" class="detail"></div>
  </section>
  <footer id="integrity"></footer>
</main>
<script id="arl-data" type="application/json">{serialized}</script>
<script>
const DATA=JSON.parse(document.getElementById('arl-data').textContent);
const $=id=>document.getElementById(id);
const esc=value=>String(value??'—').replace(/[&<>"']/g,ch=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
const short=value=>value?`${{value.slice(0,12)}}…`: '—';
const filters=['domain','runtime','condition','outcome'];
for(const key of filters){{
  for(const value of [...new Set(DATA.episodes.map(item=>item[key]))].sort()){{
    const option=document.createElement('option');option.value=value;option.textContent=value;$(key).append(option);
  }}
  $(key).addEventListener('change',render);
}}
$('search').addEventListener('input',render);
const aggregate=DATA.aggregate;
$('metrics').innerHTML=[
  ['Completed',`${{DATA.progress.completed_count}} / ${{DATA.progress.total_count}}`],
  ['Compatible recovery',`${{Math.round(aggregate.compatible_recovery_rate_delta*100)}}% delta`],
  ['Resume preserved',DATA.resume.preexisting_results_preserved?'YES':'NO'],
  ['External calls',DATA.metadata.external_network_calls]
].map(([label,value])=>`<div class="metric"><span>${{esc(label)}}</span><strong>${{esc(value)}}</strong></div>`).join('');
function selected(){{return Object.fromEntries(filters.map(key=>[key,$(key).value]));}}
function render(){{
  const query=$('search').value.trim().toLowerCase(),pick=selected();
  const visible=DATA.episodes.filter(item=>filters.every(key=>!pick[key]||item[key]===pick[key])&&(!query||JSON.stringify(item).toLowerCase().includes(query)));
  $('rows').innerHTML=visible.map(item=>`<tr data-id="${{esc(item.episode_id)}}"><td class="mono">${{esc(item.episode_id)}}</td><td>${{esc(item.domain)}}</td><td class="mono">${{esc(item.runtime)}}</td><td>${{esc(item.condition)}}</td><td><span class="pill ${{esc(item.outcome)}}">${{esc(item.outcome)}}</span></td><td class="mono">${{esc(item.failure_code)}}</td><td class="mono">${{item.events.length}}</td></tr>`).join('');
  $('empty').hidden=visible.length!==0;
  for(const row of $('rows').querySelectorAll('tr'))row.addEventListener('click',()=>show(row.dataset.id,row));
}}
function show(id,row){{
  const item=DATA.episodes.find(value=>value.episode_id===id);if(!item)return;
  for(const element of $('rows').querySelectorAll('tr'))element.classList.toggle('active',element===row);
  $('detail').classList.add('visible');
  $('detail').innerHTML=`<div class="detail-head"><div><div class="eyebrow">Episode evidence</div><h2>${{esc(item.episode_id)}}</h2></div><span class="pill ${{esc(item.outcome)}}">${{esc(item.outcome)}}</span></div>
  <div class="digest-grid"><div class="digest"><b>Initial state</b><code title="${{esc(item.initial_state_hash)}}">${{esc(short(item.initial_state_hash))}}</code></div><div class="digest"><b>Final state</b><code title="${{esc(item.final_state_hash)}}">${{esc(short(item.final_state_hash))}}</code></div><div class="digest"><b>Trace SHA-256</b><code title="${{esc(item.trace_sha256)}}">${{esc(short(item.trace_sha256))}}</code></div></div>
  <div class="events">${{item.events.map((event,index)=>`<div class="event"><span>#${{String(index+1).padStart(2,'0')}}</span><span class="type">${{esc(event.event_type)}}</span><span>${{esc(event.tool_name||event.actor)}}</span><span class="error">${{esc(event.error_code||event.fault_id)}}</span></div>`).join('')}}</div>`;
}}
$('integrity').textContent=`${{DATA.metadata.trace_payload_policy}} · model calls: ${{DATA.metadata.model_calls}} · study: ${{DATA.metadata.study_id}}`;
render();
</script>
</body>
</html>
"""
