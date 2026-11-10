"""
Turns results/r_*.csv into persona tables, significance tests and charts.

Three comparisons answer three questions:
  traffix vs actuated        does the system beat a strong standard controller?
  traffix vs junction_only   what does the supermaster (cooperation) add?
  traffix vs traffix_rules   what do the trained models add?

bus_first() answers the GSC question with confidence intervals:
  traffix vs fixed_retimed   does TraffiX beat what a city can do today without AI (retiming)?
"""
import glob
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from scipy import stats

from ..core import config

OUT = config.path("results")
CTRL = ["fixed", "fixed_retimed", "actuated", "junction_only", "traffix_rules", "traffix", "traffix_predictive", "traffix_rl", "traffix_bus_first"]
COLORS = {"fixed": "#9e9e9e", "fixed_retimed": "#5f5f5f", "actuated": "#5c8ac9", "junction_only": "#e3a046",
          "traffix_rules": "#8fbcb8", "traffix": "#1f6f6b", "traffix_predictive": "#9b6bd1",
          "traffix_rl": "#d1608a", "traffix_bus_first": "#2e8b3a"}
PERSONA_METRICS = [
    ("Ferjani (pedestrian)", "ped_mean_wait_s", "pedestrian wait (s)"),
    ("Ferjani (pedestrian)", "clearance_truncations", "clearance truncations"),
    ("Faycel (car driver)", "veh_mean_wait_s", "car wait (s)"),
    ("Faycel (car driver)", "veh_p95_travel_s", "P95 trip (s)"),
    ("Faycel (car driver)", "veh_unfinished", "unfinished trips"),
    ("Bus driver / Mamadou", "bus_headway_cv", "bus headway variation"),
    ("Bus driver / Mamadou", "bus_mean_travel_s", "bus trip (s)"),
    ("Touhami (ambulance)", "ambulance_mean_travel_s", "ambulance trip (s)"),
    ("Touhami (ambulance)", "ambulance_mean_wait_s", "ambulance stopped (s)"),
    ("Sustainability", "co2_g_per_trip", "CO2 per trip (g)"),
    ("Bus-First", "person_mean_delay_s", "delay per person (s)"),
    ("Bus-First", "bus_mean_time_loss_s", "bus time loss (s)"),
    ("Bus-First", "fuel_g_per_person_km", "fuel per person-km (g)"),
    ("Bus-First", "co2_g_per_person_km", "CO2 per person-km (g)"),
]

# The metrics a sustainability jury asks for, lower is better for all of them.
BUS_FIRST = [("person_mean_delay_s", "delay per person (s)"),
             ("bus_mean_time_loss_s", "bus time loss (s)"),
             ("veh_mean_wait_s", "car wait (s)"),
             ("ped_mean_wait_s", "pedestrian wait (s)"),
             ("fuel_g_per_person_km", "fuel per person-km (g)"),
             ("co2_g_per_person_km", "CO2 per person-km (g)"),
             ("veh_mean_stops", "stops per car"),
             ("clearance_truncations", "greens started on walkers"),
             ("ambulance_mean_travel_s", "ambulance trip (s)")]


def load():
    main = os.path.join(OUT, "results.csv")
    if os.path.exists(main):                       # the full run from run_experiments.py
        return pd.read_csv(main)
    files = sorted(glob.glob(os.path.join(OUT, "r_*.csv")))
    return pd.concat([pd.read_csv(f) for f in files], ignore_index=True) if files else None


def paired(df, col, a, b, scen):
    x = df[(df.scenario == scen) & (df.controller == a)].sort_values("seed")[col]
    y = df[(df.scenario == scen) & (df.controller == b)].sort_values("seed")[col]
    if len(x) < 2 or len(x) != len(y) or x.isna().all():
        return None
    p = stats.ttest_rel(x, y).pvalue
    return x.mean(), y.mean(), (x.mean() - y.mean()) / max(y.mean(), 1e-9) * 100, p


def run():
    df = load()
    if df is None:
        print("No results yet: run scripts/run_experiments.py first")
        return
    scen = list(dict.fromkeys(df.scenario))
    rows = []
    for persona, col, label in PERSONA_METRICS:
        for s in scen:
            for c in CTRL:
                v = df[(df.scenario == s) & (df.controller == c)][col].dropna()
                if len(v):
                    rows.append({"persona": persona, "measure": label, "scenario": s, "controller": c,
                                 "mean": round(v.mean(), 2), "std": round(v.std(), 2)})
    summary = pd.DataFrame(rows)
    summary.to_csv(os.path.join(OUT, "summary_by_persona.csv"), index=False)
    pd.set_option("display.width", 220, "display.max_rows", 400)
    for col, label in [("veh_mean_wait_s", "Car wait (s)"), ("ped_mean_wait_s", "Pedestrian wait (s)"),
                       ("clearance_truncations", "Clearance truncations")]:
        print(f"\n{label}")
        print(df.pivot_table(index="scenario", columns="controller", values=col, sort=False)
              .reindex(columns=[c for c in CTRL if c in df.controller.unique()]).round(1))

    print("\nSignificance (paired t-tests over seeds; * = p < 0.05)")
    tests = []
    for a, b, q in [("traffix", "fixed_retimed", "vs retimed (no-AI baseline)"),
                    ("traffix", "actuated", "vs actuated"), ("traffix", "junction_only", "supermaster adds"),
                    ("traffix", "traffix_rules", "models add"),
                    ("traffix_predictive", "traffix", "predictive vs max-pressure"),
                    ("traffix_rl", "traffix", "RL vs max-pressure")]:
        for col in ("veh_mean_wait_s", "ped_mean_wait_s", "ambulance_mean_travel_s"):
            for s in scen:
                r = paired(df, col, a, b, s)
                if r:
                    tests.append({"comparison": q, "metric": col, "scenario": s, "traffix": round(r[0], 2),
                                  "other": round(r[1], 2), "change_%": round(r[2], 1), "p": round(r[3], 4)})
    t = pd.DataFrame(tests)
    t.to_csv(os.path.join(OUT, "significance.csv"), index=False)
    if len(t):
        print(t[t.p < 0.05].to_string(index=False))

    panels = [("ped_mean_wait_s", "Ferjani: pedestrian wait (s)"),
              ("clearance_truncations", "Ferjani: clearance truncations"),
              ("veh_mean_wait_s", "Faycel: car wait (s)"), ("veh_p95_travel_s", "Faycel: P95 trip (s)"),
              ("bus_headway_cv", "Buses: headway variation"), ("co2_g_per_trip", "CO2 per trip (g)")]
    present = [c for c in CTRL if c in df.controller.unique()]
    fig, axes = plt.subplots(3, 2, figsize=(16, 13))
    w = 0.8 / len(present)
    for ax, (col, title) in zip(axes.flat, panels):
        for i, c in enumerate(present):
            g = df[df.controller == c].groupby("scenario")[col]
            m, sd = g.mean().reindex(scen), g.std().reindex(scen)
            ax.bar([j + (i - len(present) / 2 + 0.5) * w for j in range(len(scen))], m, w,
                   yerr=sd, capsize=2, color=COLORS[c], label=c)
        ax.set_xticks(range(len(scen)))
        ax.set_xticklabels(scen, rotation=30, ha="right", fontsize=8)
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.3)
    h, l = axes[0, 0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=len(present), bbox_to_anchor=(0.5, 0.97))
    fig.suptitle("TraffiX on a schematic central-Tunis network. Simulation, not a Tunis measurement.")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(os.path.join(OUT, "persona_charts.png"), dpi=120)
    print("\nSaved results/summary_by_persona.csv, significance.csv, persona_charts.png")
    bus_first(df)


def holm(pvalues):
    """Holm-Bonferroni adjusted p-values (many scenarios x metrics are tested at once)."""
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    adj, running = [0.0] * len(pvalues), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(pvalues) - rank) * pvalues[i]))
        adj[i] = running
    return adj


def bus_first(df, a="traffix", baselines=("fixed_retimed", "actuated", "fixed")):
    """Paired difference with 95% CI for every Bus-First metric, scenario and baseline.

    Writes results/bus_first.csv and results/bus_first.md. A change is reported as real only when
    the Holm-adjusted p-value is below 0.05; everything else is 'no clear difference'."""
    rows = []
    for b in baselines:
        if b not in set(df.controller):
            continue
        for s in dict.fromkeys(df.scenario):
            for col, label in BUS_FIRST:
                if col not in df:
                    continue
                x = df[(df.scenario == s) & (df.controller == a)].set_index("seed")[col]
                y = df[(df.scenario == s) & (df.controller == b)].set_index("seed")[col]
                d = (x - y).dropna()
                if len(d) < 3 or d.std() == 0 and d.mean() == 0:
                    continue
                half = stats.t.ppf(0.975, len(d) - 1) * d.std(ddof=1) / len(d) ** 0.5
                base = y.loc[d.index].mean()
                rows.append({"baseline": b, "scenario": s, "metric": label, "n_seeds": len(d),
                             "traffix": x.loc[d.index].mean(), "baseline_mean": base,
                             "diff": d.mean(), "ci_low": d.mean() - half, "ci_high": d.mean() + half,
                             "change_%": d.mean() / base * 100 if base else float("nan"),
                             "p": stats.ttest_rel(x.loc[d.index], y.loc[d.index]).pvalue})
    if not rows:
        return None
    t = pd.DataFrame(rows)
    t["p"] = t["p"].fillna(1.0)
    t["p_holm"] = holm(list(t["p"]))
    t["verdict"] = ["better" if p < 0.05 and dm < 0 else "worse" if p < 0.05 and dm > 0 else "no clear difference"
                    for p, dm in zip(t["p_holm"], t["diff"])]
    t = t.round({"traffix": 2, "baseline_mean": 2, "diff": 2, "ci_low": 2, "ci_high": 2, "change_%": 1,
                 "p": 4, "p_holm": 4})
    t.to_csv(os.path.join(OUT, "bus_first.csv"), index=False)
    with open(os.path.join(OUT, "bus_first.md"), "w", encoding="utf-8") as f:
        f.write("# TraffiX Bus-First evidence (simulation, synthetic demand)\n\n"
                "Paired seeds; diff = traffix minus baseline (negative is better); 95% CI of the paired diff;"
                " verdict uses Holm-adjusted p < 0.05. Occupancy is assumed (config/simulation.yaml)."
                " Fuel and CO2 are SUMO/HBEFA proxies, not measurements.\n\n")
        for b in t.baseline.unique():
            f.write(f"## traffix vs {b}\n\n| scenario | metric | traffix | {b} | change | 95% CI of diff | verdict |\n"
                    "|---|---|---|---|---|---|---|\n")
            for r in t[t.baseline == b].to_dict("records"):
                f.write(f"| {r['scenario']} | {r['metric']} | {r['traffix']} | {r['baseline_mean']} |"
                        f" {r['change_%']:+.1f}% | [{r['ci_low']}, {r['ci_high']}] | {r['verdict']} |\n")
            f.write("\n")
    print(f"Saved results/bus_first.csv and bus_first.md ({(t.verdict != 'no clear difference').sum()} clear results)")
    return t
