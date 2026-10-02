"""README table rendering from a committed aggregate (wave 4 Task 34, W4-13/W4-14).

``render_tables(aggregate)`` turns the pinned aggregate JSON into the
deterministic markdown block the README carries between the START and END
markers. No number is hand-typed anywhere: the block is generated, and
``python -m og.eval readme-tables --check README.md`` fails when the README
and the committed results file disagree.

Copy rules: no em dashes, no dates or run ids (the aggregate's file name and
the repo history carry provenance), plain markdown tables only.
"""

from __future__ import annotations

from typing import Any

START = "<!-- og:tables:start -->"
END = "<!-- og:tables:end -->"


def _pct(v: Any) -> str:
    """A proportion as a percentage; None (not measurable) as a dash."""
    return "-" if v is None else f"{100 * v:.1f}%"


def _usd(v: Any) -> str:
    return "-" if v is None else f"{v:.4f}"


def _int(v: Any) -> str:
    return "-" if v is None else str(v)


def _ratio(v: Any) -> str:
    return "-" if v is None else f"{v:.3f}"


def _extraction(agg: dict[str, Any], out: list[str]) -> None:
    ext = agg.get("extraction") or {}
    out.append(f"### Extraction: {ext.get('doc_id', '-')}")
    out.append("")
    out.append(
        "Reference set: model-drafted, human-spot-checked, scope sampled."
        " Precision is a lower bound (unlabeled predictions count as false positives)."
    )
    out.append("")
    score = ext.get("score") or {}
    per_type = score.get("per_type") or {}
    out.append("| type | gold | pred | tp | fp | fn | recall | precision (lower bound) |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for t in sorted(per_type):
        b = per_type[t]
        tp, fp, fn = b["tp"], b["fp"], b["fn"]
        out.append(
            f"| {t} | {tp + fn} | {tp + fp} | {tp} | {fp} | {fn}"
            f" | {_pct(b['recall'])} | {_pct(b.get('precision_lower_bound'))} |"
        )
    micro = score.get("micro") or {}
    macro = score.get("macro") or {}
    lower = score.get("precision_lower_bound") or {}
    out.append(
        f"| micro | {micro.get('tp', 0) + micro.get('fn', 0)} |"
        f" {micro.get('tp', 0) + micro.get('fp', 0)} | {micro.get('tp', 0)}"
        f" | {micro.get('fp', 0)} | {micro.get('fn', 0)} | {_pct(micro.get('recall'))}"
        f" | {_pct(lower.get('micro'))} |"
    )
    out.append(
        f"| macro | - | - | - | - | - | {_pct(macro.get('recall'))} | {_pct(lower.get('macro'))} |"
    )
    out.append("")
    out.append(
        "Grounding integrity (visible obligations without a grounded citation):"
        f" {ext.get('integrity', '-')}"
    )
    out.append("")
    fields = score.get("fields") or {}
    if fields:
        out.append("| field | coverage | accuracy on known pairs |")
        out.append("|---|---:|---:|")
        for f in sorted(fields):
            b = fields[f]
            out.append(f"| {f} | {_pct(b.get('coverage'))} | {_pct(b.get('accuracy_on_known'))} |")
        out.append("")


def _historical(agg: dict[str, Any], out: list[str]) -> None:
    hist = (agg.get("extraction") or {}).get("historical") or {}
    summary = hist.get("summary") or {}
    out.append("### Historical extraction variance (wave 2, n = 3)")
    out.append("")
    out.append(f"Source: `{hist.get('source', '-')}` (committed; not this run).")
    out.append("")
    stats = summary.get("aggregate") or {}
    out.append("| metric | mean | sd | min | max |")
    out.append("|---|---:|---:|---:|---:|")
    for name in sorted(stats):
        b = stats[name]
        if not isinstance(b, dict):
            continue
        out.append(
            f"| {name} | {_ratio(b.get('mean'))} | {_ratio(b.get('sd'))}"
            f" | {_ratio(b.get('min'))} | {_ratio(b.get('max'))} |"
        )
    out.append("")


def _drops(agg: dict[str, Any], out: list[str]) -> None:
    drops = agg.get("drops") or {}
    by_reason = drops.get("by_reason") or {}
    out.append("### Grounding drops (current extraction runs)")
    out.append("")
    out.append("| reason | count |")
    out.append("|---|---:|")
    if by_reason:
        for reason in sorted(by_reason):
            out.append(f"| {reason} | {by_reason[reason]} |")
    else:
        out.append("| (none) | 0 |")
    out.append(f"| total | {sum(by_reason.values())} |")
    out.append("")


def _gates_row(name: str, b: dict[str, Any], extra: str) -> str:
    ref = b.get("vs_reference") or {}
    base = b.get("vs_baseline") or {}
    return (
        f"| {name} | {_pct(ref.get('recall'))} | {_ratio(ref.get('miss_upper_95'))}"
        f" | {_pct(ref.get('precision'))} | {_pct(base.get('recall'))}"
        f" | {_pct(base.get('precision'))} | {extra} |"
    )


def _change(agg: dict[str, Any], out: list[str]) -> None:
    for co in sorted(agg.get("change") or {}):
        block = agg["change"][co]
        out.append(f"### Change order: {co}")
        out.append("")
        findings = block.get("findings") or {}
        out.append(
            "Findings (one per kind, new segment, and old side; duplicates across"
            " categories count once):"
        )
        out.append("")
        out.append("| mode | gold | predicted | tp | fp | fn | precision | recall |")
        out.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for mode in ("ungated", "gated"):
            b = (findings.get(mode) or {}).get("overall") or {}
            out.append(
                f"| {mode} | {b.get('gold', '-')} | {b.get('predicted', '-')}"
                f" | {b.get('tp', '-')} | {b.get('fp', '-')} | {b.get('fn', '-')}"
                f" | {_pct(b.get('precision'))} | {_pct(b.get('recall'))} |"
            )
        out.append("")
        out.append(f"Gated retention of ungated findings: {_pct(findings.get('retention_recall'))}")
        out.append("")
        gates = block.get("gates") or {}
        out.append("Gates (a skip may only save work, never suppress a finding):")
        out.append("")
        out.append(
            "| backend | recall vs reference | miss upper 95 | precision vs reference"
            " | recall vs baseline | precision vs baseline | notes |"
        )
        out.append("|---|---:|---:|---:|---:|---:|---|")
        cascade = gates.get("cascade") or {}
        ref = cascade.get("vs_reference") or {}
        out.append(
            _gates_row(
                "cascade",
                cascade,
                f"skipped {ref.get('skipped', '-')} of 6 ({_pct(ref.get('skip_rate'))})",
            )
        )
        out.append(_gates_row("rules", gates.get("rules") or {}, "tier 1"))
        haiku = gates.get("haiku") or {}
        out.append(
            _gates_row(
                "haiku",
                haiku,
                f"coverage {_pct(haiku.get('coverage'))}; recall null without positives",
            )
        )
        out.append("")
        skips = block.get("skips") or []
        out.append("Skipped checks:")
        out.append("")
        out.append("| category | kind | reference answer | ungated findings in category |")
        out.append("|---|---|---|---:|")
        if skips:
            for s in sorted(skips, key=lambda s: (s["category"], s["kind"])):
                out.append(
                    f"| {s['category']} | {s['kind']} | {s['reference']}"
                    f" | {s['baseline_findings']} |"
                )
        else:
            out.append("| (none: every check ran) | - | - | - |")
        out.append("")
        disagreements = block.get("disagreements") or []
        out.append(f"Gate disagreements with the reference: {len(disagreements)}")
        out.append("")
        cost = block.get("cost") or {}
        out.append("| mode | recorded usd | incremental usd | recorded latency ms |")
        out.append("|---|---:|---:|---:|")
        for mode in ("ungated", "gated"):
            out.append(
                f"| {mode} | {_usd((cost.get('recorded_usd') or {}).get(mode))}"
                f" | {_usd((cost.get('incremental_usd') or {}).get(mode))}"
                f" | {_int((cost.get('recorded_latency_ms') or {}).get(mode))} |"
            )
        out.append("")


def _totals(agg: dict[str, Any], out: list[str]) -> None:
    cost = agg.get("cost") or {}
    out.append("### Cost totals (change orders)")
    out.append("")
    out.append(f"Change orders scored: {_int(cost.get('change_orders'))}")
    out.append("")
    out.append("| mode | recorded usd | incremental usd | recorded latency ms |")
    out.append("|---|---:|---:|---:|")
    for mode in ("ungated", "gated"):
        out.append(
            f"| {mode} | {_usd((cost.get('recorded_usd') or {}).get(mode))}"
            f" | {_usd((cost.get('incremental_usd') or {}).get(mode))}"
            f" | {_int((cost.get('recorded_latency_ms') or {}).get(mode))} |"
        )
    out.append("")
    out.append(
        "Generated from the pinned aggregate by `python -m og.eval readme-tables`."
        " Edit the results file, never this block."
    )
    out.append("")


def render_tables(aggregate: dict[str, Any]) -> str:
    """The deterministic markdown block for the README, ending in one newline."""
    out: list[str] = []
    _extraction(aggregate, out)
    _historical(aggregate, out)
    _drops(aggregate, out)
    _change(aggregate, out)
    _totals(aggregate, out)
    return "\n".join(out)
