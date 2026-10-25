"""Leaderboard (DE and EN), static results page and README headline from the committed run recordings.

Deterministic by construction: no clock, sorted inputs, numbers formatted here, LF line endings. Planned
configurations without a real run are shown as pending; synthetic pipeline-test runs have their own section and
are never ranked as a model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from energie_sql_bench import __version__
from energie_sql_bench.config import PlannedConfig, Settings
from energie_sql_bench.files import read_json
from energie_sql_bench.questions import load_questions
from energie_sql_bench.scoring import METHODOLOGY_NOTE, majority_by_item, mcnemar_exact, paired_discordant
from energie_sql_bench.taxonomy import label_counts, load_labels

PENDING = {"de": "ausstehend: Live-Lauf", "en": "pending: live run"}
SYNTHETIC_LABEL = {
    "de": "Pipeline-Test (synthetisch, kein Sprachmodell)",
    "en": "Pipeline test (synthetic, no language model)",
}
HEADLINE_START = "<!-- esb:headline:start -->"
HEADLINE_END = "<!-- esb:headline:end -->"
REPO_URL = "https://github.com/HARISPAARTAN/energie-sql-bench"
MODEL_NAMES = {
    "claude-haiku-5-5": "Claude Haiku 5.5",
    "claude-sonnet-5-5": "Claude Sonnet 5.5",
    "claude-opus-5-5": "Claude Opus 5.5",
    "qwen2.5-coder:7b": "Qwen2.5-Coder 7B (Ollama)",
}
SCHEMA_NAMES = {
    "de": {"full": "volles Schema", "oracle": "Orakel-Tabellen", "retrieved": "abgerufene Tabellen"},
    "en": {"full": "full schema", "oracle": "oracle tables", "retrieved": "retrieved tables"},
}
TAXONOMY = {
    "de": {
        "E0": "Providerfehler",
        "E1": "Syntax oder Dialekt",
        "E2": "erfundene Tabelle oder Spalte",
        "E3": "falscher oder fehlender Join",
        "E4": "falsche Granularität oder Aggregation",
        "E5": "Zeitlogik",
        "E6": "Wert oder Synonym",
        "E7": "Einheit oder Skala",
        "E8": "NULL-Behandlung",
        "E9": "Sortierung oder Begrenzung",
        "E10": "Form der Projektion",
        "E11": "vom Guard blockiert",
        "E12": "Enthaltungsfehler",
        "E13": "Timeout oder Zeilenlimit",
        "E?": "falsch, noch nicht kategorisiert",
    },
    "en": {
        "E0": "provider error",
        "E1": "syntax or dialect",
        "E2": "hallucinated table or column",
        "E3": "wrong or missing join",
        "E4": "wrong grain or aggregation",
        "E5": "time logic",
        "E6": "value or synonym",
        "E7": "unit or scale",
        "E8": "NULL handling",
        "E9": "ordering or limit",
        "E10": "projection shape",
        "E11": "blocked by the guard",
        "E12": "abstention error",
        "E13": "timeout or row cap",
        "E?": "wrong, not yet labelled",
    },
}
CHART_WIDTH = 560
CHART_ROW = 26
CHART_X0 = 190
MODEL_SHORT = {
    "claude-haiku-5-5": "Haiku 5.5",
    "claude-sonnet-5-5": "Sonnet 5.5",
    "claude-opus-5-5": "Opus 5.5",
    "qwen2.5-coder:7b": "Qwen 7B",
}


@dataclass(frozen=True)
class RunView:
    run_id: str
    key: str
    provider: str
    model: str
    variant: str
    self_correct: bool
    split: str
    synthetic: bool
    created: str
    summary: dict[str, Any]


def label_sort_key(label: str) -> tuple[int, int]:
    """E0 < E1 < ... < E13 < E?"""
    return (0, int(label[1:])) if label[1:].isdigit() else (1, 0)


def fmt_num(x: float | None, digits: int, lang: str) -> str:
    if x is None:
        return "–"
    text = f"{x:,.{digits}f}"
    if lang == "de":
        text = text.translate(str.maketrans({",": ".", ".": ","}))
    return text


def fmt_pct(x: float | None, lang: str) -> str:
    return "–" if x is None else f"{fmt_num(100 * x, 1, lang)} %"


def fmt_p(p: float, lang: str) -> str:
    return fmt_num(p, 4, lang) if p >= 0.0001 else ("< 0,0001" if lang == "de" else "< 0.0001")


def config_label(
    provider: str, model: str, variant: str, self_correct: bool, settings: Settings, lang: str
) -> str:
    spec = settings.variants.get(variant)
    parts = [SCHEMA_NAMES[lang].get(spec.schema, spec.schema)] if spec else []
    if spec and spec.semantic:
        parts.append("Semantik" if lang == "de" else "semantic layer")
    if spec and spec.fewshot:
        parts.append("Few-Shot")
    detail = " + ".join(parts)
    text = (
        f"{MODEL_NAMES.get(model, model)} · {variant} ({detail})"
        if detail
        else f"{MODEL_NAMES.get(model, model)} · {variant}"
    )
    if self_correct:
        text += " · Selbstkorrektur" if lang == "de" else " · self-correction"
    return text


def load_runs(settings: Settings) -> list[RunView]:
    root = settings.path("results/runs")
    if not root.is_dir():
        return []
    runs = []
    for run_dir in sorted(p for p in root.iterdir() if (p / "config.json").is_file()):
        cfg = read_json(run_dir / "config.json")
        spec = cfg["spec"]
        key = f"{spec['provider']}|{spec['model']}|{spec['variant']}|{int(spec['self_correct'])}"
        runs.append(
            RunView(
                run_dir.name,
                key,
                spec["provider"],
                spec["model"],
                spec["variant"],
                bool(spec["self_correct"]),
                spec["split"],
                bool(cfg["synthetic"]),
                cfg["created"],
                read_json(run_dir / "summary.json"),
            )
        )
    return runs


def select_runs(runs: list[RunView], planned: tuple[PlannedConfig, ...]) -> list[tuple[str, RunView | None]]:
    """(key, newest complete real test run or None) for every planned key, then unplanned real runs."""
    eligible = [r for r in runs if not r.synthetic and r.split == "test" and r.summary["complete"]]
    chosen: list[tuple[str, RunView | None]] = []
    for plan in planned:
        matches = sorted((r for r in eligible if r.key == plan.key), key=lambda r: (r.created, r.run_id))
        chosen.append((plan.key, matches[-1] if matches else None))
    planned_keys = {p.key for p in planned}
    extra = sorted(
        (r for r in eligible if r.key not in planned_keys), key=lambda r: (r.key, r.created, r.run_id)
    )
    newest: dict[str, RunView] = {r.key: r for r in extra}
    chosen.extend((key, run) for key, run in sorted(newest.items()))
    return chosen


def _metrics(run: RunView, lang: str) -> dict[str, Any]:
    s = run.summary
    ex, strict = s["ex"], s["ex_strict"]
    lat = s["latency_ms"]
    abst = s["abstention"]
    return {
        "abstention": f"{fmt_pct(abst['precision'], lang)} / {fmt_pct(abst['recall'], lang)}",
        "blocked": str(s["blocked_attempts"]),
        "created": run.created,
        "db_ms": f"{fmt_num(lat['db_p50'], 0, lang)} / {fmt_num(lat['db_p95'], 0, lang)}",
        "ex": f"{fmt_pct(ex['mean'], lang)} ({fmt_pct(ex['ci95'][0], lang)}–{fmt_pct(ex['ci95'][1], lang)})",
        "ex_mean": ex["mean"],
        "ex_lo": ex["ci95"][0],
        "ex_hi": ex["ci95"][1],
        "ex_strict": fmt_pct(strict["mean"], lang),
        "llm_ms": f"{fmt_num(lat['llm_p50'], 0, lang)} / {fmt_num(lat['llm_p95'], 0, lang)}",
        "n": f"{ex['correct']}/{ex['n']}",
        "repeats": s["repeats"],
        "run_id": run.run_id,
        "spread": f"{fmt_pct(ex['min'], lang)}–{fmt_pct(ex['max'], lang)}" if s["repeats"] > 1 else "–",
        "tokens": fmt_num(sum(int(v) for v in s["tokens"].values()), 0, lang),
        "usd": fmt_num(s["cost"]["usd"], 4, lang),
        "usd_per_correct": fmt_num(s["cost"]["usd_per_correct"], 5, lang),
        "validity": fmt_pct(s["validity"]["rate"], lang),
    }


def leaderboard_rows(
    chosen: list[tuple[str, RunView | None]], settings: Settings, lang: str
) -> list[dict[str, Any]]:
    rows = []
    for key, run in chosen:
        plan = PlannedConfig.parse(key)
        short = f"{MODEL_SHORT.get(plan.model, plan.model)} · {plan.variant}"
        if plan.self_correct:
            short += " · SK" if lang == "de" else " · SC"
        row: dict[str, Any] = {
            "key": key,
            "label": config_label(plan.provider, plan.model, plan.variant, plan.self_correct, settings, lang),
            "short": short,
            "pending": run is None,
        }
        if run is None:
            row.update({"ex": PENDING[lang], "ex_mean": None})
        else:
            row.update(_metrics(run, lang))
        rows.append(row)
    return rows


def _majority(run: RunView) -> dict[str, bool]:
    """Per-item majority outcome (strictly more than half of the repeats correct): the unit of a paired test is
    the item, never an (item, repeat) pair."""
    return majority_by_item((i["item_id"], bool(i["correct"])) for i in run.summary["items"])


def _paired(a: RunView, b: RunView) -> tuple[int, int, int]:
    return paired_discordant(_majority(a), _majority(b))


def comparison_rows(
    chosen: list[tuple[str, RunView | None]], settings: Settings, lang: str
) -> list[dict[str, Any]]:
    by_key = dict(chosen)
    rows = []
    for key_a, key_b in settings.report.comparisons:
        pa, pb = PlannedConfig.parse(key_a), PlannedConfig.parse(key_b)
        row: dict[str, Any] = {
            "a": config_label(pa.provider, pa.model, pa.variant, pa.self_correct, settings, lang),
            "b": config_label(pb.provider, pb.model, pb.variant, pb.self_correct, settings, lang),
        }
        run_a, run_b = by_key.get(key_a), by_key.get(key_b)
        if run_a is None or run_b is None:
            row.update({"pairs": "–", "a_only": "–", "b_only": "–", "p": PENDING[lang]})
        else:
            n, a_only, b_only = _paired(run_a, run_b)
            row.update(
                {
                    "pairs": str(n),
                    "a_only": str(a_only),
                    "b_only": str(b_only),
                    "p": fmt_p(mcnemar_exact(a_only, b_only), lang),
                }
            )
        rows.append(row)
    return rows


def synthetic_rows(runs: list[RunView], lang: str) -> list[dict[str, Any]]:
    rows = []
    for run in runs:
        if not run.synthetic:
            continue
        s = run.summary
        rows.append(
            {
                "run_id": run.run_id,
                "mode": ("Selbstkorrektur" if lang == "de" else "self-correction")
                if run.self_correct
                else ("Einzelversuch" if lang == "de" else "single shot"),
                "ex": f"{fmt_pct(s['ex']['mean'], lang)} ({s['ex']['correct']}/{s['ex']['n']})",
                "ex_mean": s["ex"]["mean"],
                "ex_strict": fmt_pct(s["ex_strict"]["mean"], lang),
                "blocked": str(s["blocked_attempts"]),
                "repairs": str(s["repair_attempts"]),
                "labels": ", ".join(f"{k} {s['labels'][k]}" for k in sorted(s["labels"], key=label_sort_key))
                or "–",
            }
        )
    return rows


def taxonomy_rows(
    runs: list[RunView], manual: dict[tuple[str, str, int], str], lang: str
) -> tuple[list[str], list[dict[str, Any]]]:
    shown = [r for r in runs if r.synthetic or (r.split == "test" and r.summary["complete"])]
    counts = {r.run_id: label_counts(r.run_id, r.summary["items"], manual) for r in shown}
    labels = sorted({label for c in counts.values() for label in c}, key=label_sort_key)
    rows = [
        {
            "label": label,
            "name": TAXONOMY[lang].get(label, label),
            "counts": [str(counts[r.run_id].get(label, 0)) for r in shown],
        }
        for label in labels
    ]
    return [r.run_id for r in shown], rows


def question_stats(settings: Settings) -> dict[str, Any]:
    questions = load_questions(settings.path("bench/questions"))
    tiers: dict[str, dict[str, int]] = {}
    for q in questions:
        tiers.setdefault(q.tier, {"test": 0, "dev": 0})[q.split] += 1
    return {
        "intents": len(questions),
        "n_items": 2 * len(questions),
        "scored": 2 * sum(q.split == "test" for q in questions),
        "tiers": [{"tier": t, "test": c["test"], "dev": c["dev"]} for t, c in sorted(tiers.items())],
    }


def parity_info(settings: Settings, lang: str) -> dict[str, Any] | None:
    path = settings.path("data/sample/parity.json")
    if not path.is_file():
        return None
    p = read_json(path)
    return {
        "coverage": fmt_pct(p["coverage"], lang),
        "matched": p["matched"],
        "intents": p["intents"],
        "nontrivial": p["matched_nontrivial"],
        "skipped": p["skipped"],
    }


def chart(rows: list[dict[str, Any]], synthetic: list[dict[str, Any]], lang: str) -> dict[str, Any]:
    bars = []
    y = 0
    for row in rows:
        bar = {"y": y, "label": row["short"], "pending": row["pending"], "synthetic": False}
        if row["pending"]:
            bar.update({"w": CHART_WIDTH, "text": PENDING[lang]})
        else:
            bar.update(
                {
                    "w": round(CHART_WIDTH * row["ex_mean"], 1),
                    "lo": round(CHART_WIDTH * row["ex_lo"], 1),
                    "hi": round(CHART_WIDTH * row["ex_hi"], 1),
                    "text": fmt_pct(row["ex_mean"], lang),
                }
            )
        bars.append(bar)
        y += CHART_ROW
    for row in synthetic:
        bars.append(
            {
                "y": y,
                "label": row["run_id"],
                "pending": False,
                "synthetic": True,
                "w": round(CHART_WIDTH * row["ex_mean"], 1),
                "text": fmt_pct(row["ex_mean"], lang),
            }
        )
        y += CHART_ROW
    ticks = [{"x": CHART_X0 + CHART_WIDTH * t // 100, "text": f"{t} %"} for t in (0, 25, 50, 75, 100)]
    return {
        "bars": bars,
        "height": y + 30,
        "x0": CHART_X0,
        "total": CHART_X0 + CHART_WIDTH + 70,
        "ticks": ticks,
    }


def headline_markdown(rows: list[dict[str, Any]], synthetic: list[dict[str, Any]], lang: str) -> str:
    head = [
        "v4 = volles Schema + Semantik + Few-Shot, Einzelversuch, Testsplit (120 Items)."
        if lang == "de"
        else "v4 = full schema + semantic layer + few-shot, single shot, test split (120 items).",
        "",
    ]
    if lang == "de":
        head += [
            "| Modell | EX (95 %-KI) | Validität | USD pro richtige Antwort | Lauf |",
            "|---|---|---|---|---|",
        ]
    else:
        head += [
            "| Model | EX (95 % CI) | Validity | USD per correct answer | Run |",
            "|---|---|---|---|---|",
        ]
    for row in rows:
        plan = PlannedConfig.parse(row["key"])
        if plan.variant != "v4" or plan.self_correct:
            continue
        name = MODEL_NAMES.get(plan.model, plan.model)
        if row["pending"]:
            head.append(f"| {name} | {PENDING[lang]} | – | – | – |")
        else:
            head.append(
                f"| {name} | {row['ex']} | {row['validity']} | {row['usd_per_correct']} | `{row['run_id']}` |"
            )
    if synthetic:
        head.append("")
    for row in synthetic:
        note = (
            "prüft nur die Harness, kein Modellergebnis"
            if lang == "de"
            else "tests the harness only, not a model result"
        )
        head.append(f"- {SYNTHETIC_LABEL[lang]}: `{row['run_id']}` ({row['mode']}) EX {row['ex']}, {note}.")
    return "\n".join(head)


def replace_headline(text: str, block: str) -> str:
    start, end = text.index(HEADLINE_START), text.index(HEADLINE_END)
    return text[: start + len(HEADLINE_START)] + "\n" + block + "\n" + text[end:]


def build_context(settings: Settings, lang: str) -> dict[str, Any]:
    runs = load_runs(settings)
    chosen = select_runs(runs, settings.report.planned)
    rows = leaderboard_rows(chosen, settings, lang)
    synthetic = synthetic_rows(runs, lang)
    tax_runs, tax_rows = taxonomy_rows(runs, load_labels(settings.path("analysis/labels.csv")), lang)
    snap = settings.snapshot
    return {
        "lang": lang,
        "version": __version__,
        "repo_url": REPO_URL,
        "methodology_note": METHODOLOGY_NOTE[lang],
        "pending_text": PENDING[lang],
        "synthetic_label": SYNTHETIC_LABEL[lang],
        "rows": rows,
        "real_runs": sum(1 for r in rows if not r["pending"]),
        "synthetic": synthetic,
        "comparisons": comparison_rows(chosen, settings, lang),
        "taxonomy_runs": tax_runs,
        "taxonomy_rows": tax_rows,
        "questions": question_stats(settings),
        "parity": parity_info(settings, lang),
        "chart": chart(rows, synthetic, lang),
        "snapshot": {
            "as_of": snap.as_of,
            "smard": f"{snap.smard_start} – {snap.smard_end}",
            "mastr": snap.mastr_end,
            "commit": snap.monitor_commit[:7],
        },
        "eur_usd": fmt_num(settings.cost.eur_usd, 4, lang),
        "rate_date": settings.cost.rate_date,
    }


def _env() -> Any:
    import jinja2

    return jinja2.Environment(
        loader=jinja2.PackageLoader("energie_sql_bench", "templates"),
        autoescape=jinja2.select_autoescape(["html"]),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=jinja2.StrictUndefined,
    )


def build_outputs(settings: Settings) -> dict[Path, str]:
    env = _env()
    outputs: dict[Path, str] = {}
    site = settings.path(settings.report.site_dir)
    for lang, md_path, html_name, readme in (
        ("de", settings.report.leaderboard_de, "index.html", "README.md"),
        ("en", settings.report.leaderboard_en, "en.html", "README.en.md"),
    ):
        ctx = build_context(settings, lang)
        outputs[settings.path(md_path)] = env.get_template("leaderboard.md.j2").render(ctx)
        outputs[site / html_name] = env.get_template("site.html.j2").render(ctx)
        readme_path = settings.path(readme)
        current = readme_path.read_text(encoding="utf-8")
        outputs[readme_path] = replace_headline(
            current, headline_markdown(ctx["rows"], ctx["synthetic"], lang)
        )
    return outputs


def write_outputs(outputs: dict[Path, str]) -> None:
    for path, text in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")


def stale_outputs(outputs: dict[Path, str]) -> list[Path]:
    return [p for p, text in outputs.items() if not p.is_file() or p.read_text(encoding="utf-8") != text]
