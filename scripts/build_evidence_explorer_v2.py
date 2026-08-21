#!/usr/bin/env python3
# ruff: noqa: E501
"""Generate Evidence Explorer v2 from claims and verified public evidence only."""

from __future__ import annotations

import argparse
import io
import json
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any

from arl.core.types import digest_value
from arl.evidence.bundle import load_bundle
from arl.evidence.events import count_provider_events
from arl.evidence.schema import schema_documents
from arl.evidence.verify import verify_bundle
from arl.registry import claims, studies

ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _bundle_zip(bundle: Path) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as archive:
        paths = sorted(
            (item for item in bundle.rglob("*") if item.is_file()),
            key=lambda path: path.relative_to(bundle).as_posix(),
        )
        for path in paths:
            info = zipfile.ZipInfo(path.relative_to(bundle).as_posix(), ZIP_TIMESTAMP)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, path.read_bytes())
    return output.getvalue()


def _paired_estimands(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    root = analysis.get("estimands", {})
    if isinstance(root, dict) and "unconditional_paired_fault_safe_pass_difference" in root:
        candidates = root
    else:
        candidates = {}
    values = []
    for name in (
        "unconditional_paired_fault_safe_pass_difference",
        "common_clean_fault_recovery_difference",
        "clean_safe_pass_difference",
        "severe_side_effect_risk_difference",
    ):
        item = candidates.get(name)
        if not isinstance(item, dict):
            continue
        ci = item.get("bootstrap_ci", {})
        values.append(
            {
                "name": name,
                "numerator": item.get("numerator"),
                "denominator": item.get("denominator"),
                "point_estimate": item.get("point_estimate"),
                "ci_lower": ci.get("lower") if isinstance(ci, dict) else None,
                "ci_upper": ci.get("upper") if isinstance(ci, dict) else None,
                "paired_2x2_counts": item.get("paired_2x2_counts"),
            }
        )
    return values


def build_index(project_root: Path) -> dict[str, Any]:
    """Build canonical front-end data; JavaScript performs no statistical calculation."""

    claim_by_study = {item["study_id"]: item for item in claims()}
    public: dict[str, dict[str, Any]] = {}
    evidence_root = project_root / "evidence"
    for manifest in sorted(evidence_root.glob("*/manifest.json")):
        bundle = manifest.parent
        verification = verify_bundle(bundle)
        if not verification.valid:
            raise ValueError(f"public evidence is invalid: {bundle}: {verification.errors}")
        loaded = load_bundle(bundle)
        episodes = loaded["episodes"]
        events = loaded["provider_events"]
        usage_events = [item for item in events if item["event_type"] == "ProviderUsageRecorded"]
        cost_values = [item["cost_usd"] for item in usage_events]
        public_cost = (
            0
            if not events
            else (
                str(sum((Decimal(item) for item in cost_values), start=Decimal("0")))
                if usage_events and all(item is not None for item in cost_values)
                else None
            )
        )
        terminal_attempt_events = [
            item
            for item in events
            if item["event_type"] in {"TransportAttemptFailed", "ProviderResponseReceived"}
        ]
        duration_values = [item["duration_ms"] for item in terminal_attempt_events]
        public_latency = (
            0
            if not events
            else (
                sum(int(item) for item in duration_values)
                if terminal_attempt_events and all(item is not None for item in duration_values)
                else None
            )
        )
        study_id = loaded["study"]["study_id"]
        public[study_id] = {
            "bundle": bundle.relative_to(project_root).as_posix(),
            "bundle_download": f"bundles/{study_id}.zip",
            "episode_count": len(episodes),
            "filters": {
                "models": sorted({item["model_binding"] for item in episodes}),
                "runtimes": sorted({item["runtime"] for item in episodes}),
                "domains": sorted({item["domain"] for item in episodes}),
                "faults": sorted({item["fault_family"] for item in episodes}),
            },
            "provider_counts": count_provider_events(events).as_dict(),
            "paired_estimands": _paired_estimands(loaded["analysis"]),
            "cost_usd": public_cost,
            "latency_ms": public_latency,
            "analysis_status": loaded["analysis"]["analysis_status"],
            "verification_check_count": len(verification.checks),
        }
    records = []
    for study in studies():
        claim = claim_by_study.get(study["study_id"])
        evidence = public.get(study["study_id"])
        records.append(
            {
                **study,
                "claim": claim,
                "evidence": evidence,
                "evidence_available": evidence is not None,
            }
        )
    payload = {
        "explorer_version": "evidence-explorer-v2",
        "evidence_schema_version": "arl-evidence-v1",
        "statistics_source": "Python analysis.json only; front-end does not recompute",
        "studies": records,
    }
    return {**payload, "source_digest": digest_value({**payload, "schemas": schema_documents()})}


HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'">
<title>Agent Reliability Lab · Evidence Explorer</title>
<style>
:root{color-scheme:light;--green:#16835a;--green-dark:#0d5c40;--ink:#1d2924;--muted:#607169;--line:#dbe5df;--paper:#fff;--wash:#f4f8f5;--bad:#a43b32;--warn:#94650b}
*{box-sizing:border-box}body{margin:0;background:var(--wash);color:var(--ink);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}header{background:var(--paper);border-bottom:1px solid var(--line)}.wrap{max-width:1180px;margin:auto;padding:28px 24px}.eyebrow{color:var(--green-dark);font-size:12px;font-weight:750;letter-spacing:.12em;text-transform:uppercase}h1{font-size:clamp(28px,5vw,48px);line-height:1.04;margin:8px 0 12px;letter-spacing:-.035em}h2{font-size:20px;margin:0}.lede{max-width:780px;color:var(--muted);font-size:17px}.notice{margin-top:18px;padding:12px 14px;background:#fff8e6;border:1px solid #ead8a8;border-radius:8px}.filters{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:12px;margin:20px 0}.filters label{font-size:12px;font-weight:700;color:var(--muted)}select{display:block;width:100%;margin-top:5px;padding:9px;border:1px solid var(--line);border-radius:6px;background:white}.cards{display:grid;gap:16px}.card{background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:20px;box-shadow:0 2px 8px #234b3820}.top{display:flex;gap:12px;align-items:flex-start;justify-content:space-between}.status{white-space:nowrap;border-radius:999px;padding:4px 9px;font-size:12px;font-weight:750;background:#e6f4ed;color:var(--green-dark)}.status.invalid,.status.blocked{background:#fbeae8;color:var(--bad)}.status.design_only{background:#fff4d9;color:var(--warn)}.meta{color:var(--muted);font-size:13px}.claim{margin:14px 0}.limits{color:var(--muted);font-size:13px;margin:10px 0;padding-left:20px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:14px 0}.metric{background:var(--wash);border-radius:7px;padding:10px}.metric b{display:block;font-size:18px}.metric span{font-size:12px;color:var(--muted)}table{width:100%;border-collapse:collapse;font-size:13px;margin-top:10px}th,td{text-align:left;border-top:1px solid var(--line);padding:8px 5px}code{font-size:12px}a{color:var(--green-dark)}.empty{color:var(--muted);font-style:italic}.commands{background:#12251d;color:#dff5e9;padding:10px 12px;border-radius:6px;overflow:auto}.foot{font-size:12px;color:var(--muted)}@media(max-width:760px){.filters,.metrics{grid-template-columns:1fr 1fr}.top{display:block}.status{display:inline-block;margin-top:8px}}@media(max-width:460px){.filters,.metrics{grid-template-columns:1fr}.wrap{padding:22px 15px}}
</style>
</head>
<body>
<header><div class="wrap"><div class="eyebrow">Agent Reliability Lab</div><h1>Evidence Explorer</h1><p class="lede">Claims, validity states, paired results, errors and public bundle links from one versioned evidence contract.</p><div class="notice"><b>Fail-closed status:</b> v0.28 readiness failed; v0.29 infrastructure and readiness failed. Neither is a valid confirmatory result.</div></div></header>
<main class="wrap"><div class="filters" aria-label="Evidence filters"><label>Model<select id="model"><option value="">All</option></select></label><label>Runtime<select id="runtime"><option value="">All</option></select></label><label>Domain<select id="domain"><option value="">All</option></select></label><label>Fault<select id="fault"><option value="">All</option></select></label></div><div id="cards" class="cards" aria-live="polite"></div><p class="foot" id="integrity"></p></main>
<script>
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=v=>v===null||v===undefined?'N/A':typeof v==='number'?v.toFixed(3):esc(v);
const filters={model:'models',runtime:'runtimes',domain:'domains',fault:'faults'};let DATA;
function options(){for(const [id,key] of Object.entries(filters)){const values=new Set();for(const s of DATA.studies)for(const v of s.evidence?.filters?.[key]||[])values.add(v);const node=document.getElementById(id);for(const v of [...values].sort()){const o=document.createElement('option');o.value=v;o.textContent=v;node.appendChild(o)}node.addEventListener('change',render)}}
function visible(s){if(!s.evidence)return !Object.keys(filters).some(id=>document.getElementById(id).value);return Object.entries(filters).every(([id,key])=>{const v=document.getElementById(id).value;return !v||s.evidence.filters[key].includes(v)})}
function estimands(s){const rows=s.evidence?.paired_estimands||[];if(!rows.length)return '<p class="empty">Paired counts and confidence intervals are not materialized in public arl-evidence-v1.</p>';return `<table><thead><tr><th>Estimand</th><th>n</th><th>Estimate</th><th>95% CI</th><th>Discordant R1−/R2+ · R1+/R2−</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.name)}</td><td>${esc(r.denominator)}</td><td>${fmt(r.point_estimate)}</td><td>[${fmt(r.ci_lower)}, ${fmt(r.ci_upper)}]</td><td>${esc(r.paired_2x2_counts?.r1_fail_r2_pass)} · ${esc(r.paired_2x2_counts?.r1_pass_r2_fail)}</td></tr>`).join('')}</tbody></table>`}
function limitations(s){const rows=s.claim?.limitations||[];return rows.length?`<ul class="limits">${rows.map(v=>`<li>${esc(v)}</li>`).join('')}</ul>`:''}
function card(s){const e=s.evidence,c=s.claim;const claim=c?.exact_claim_text||'No registered empirical claim.';const bundle=e?`<a href="${esc(e.bundle_download)}" download>Download bundle</a> · <a href="${esc(e.bundle)}/manifest.json">Open manifest</a> · <code>arl verify ${esc(e.bundle)}</code>`:'<span class="empty">No public episode bundle</span>';return `<article class="card"><div class="top"><div><div class="meta">${esc(s.contract_version)} · ${esc(s.analysis)}</div><h2>${esc(s.study_id)}</h2></div><span class="status ${esc(s.status)}">${esc(s.status)}</span></div><p class="claim">${esc(claim)}</p>${limitations(s)}<div class="metrics"><div class="metric"><b>${esc(e?.episode_count??'N/A')}</b><span>public episodes</span></div><div class="metric"><b>${esc(e?.provider_counts?.provider_failure_count??'N/A')}</b><span>provider failures</span></div><div class="metric"><b>${fmt(e?.cost_usd)}</b><span>public cost USD</span></div><div class="metric"><b>${fmt(e?.latency_ms)}</b><span>public latency ms</span></div></div>${estimands(s)}<p>${bundle}</p></article>`}
function render(){document.getElementById('cards').innerHTML=DATA.studies.filter(visible).map(card).join('')||'<p class="empty">No study matches these filters.</p>'}
fetch('evidence-index.json').then(r=>{if(!r.ok)throw new Error('index unavailable');return r.json()}).then(data=>{DATA=data;options();render();document.getElementById('integrity').textContent=`${data.explorer_version} · ${data.evidence_schema_version} · source ${data.source_digest}`}).catch(error=>{document.getElementById('cards').textContent=`Evidence index failed closed: ${error.message}`});
</script>
</body></html>
"""


def _payload(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    expected = {
        root / "site/evidence-index.json": _payload(build_index(root)),
        root / "site/index.html": HTML.encode("utf-8"),
    }
    for manifest in sorted((root / "evidence").glob("*/manifest.json")):
        bundle = manifest.parent
        expected[root / "site/bundles" / f"{bundle.name}.zip"] = _bundle_zip(bundle)
    if args.check:
        failures = [
            str(path.relative_to(root))
            for path, data in expected.items()
            if not path.is_file() or path.read_bytes() != data
        ]
        if failures:
            print(f"Evidence Explorer outputs are stale: {', '.join(failures)}")
            return 1
        print("Evidence Explorer v2 outputs match claims and public schema")
        return 0
    for path, data in expected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print("Generated Evidence Explorer v2 from claims and verified public evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
