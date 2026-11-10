"""
Runs controllers x scenarios x seeds and saves results/results.csv.

  python scripts/run_experiments.py
  python scripts/run_experiments.py --scenario emergency --controller traffix --seeds 1
  python scripts/run_experiments.py --gui --scenario rain --controller traffix --seeds 1

Results are saved after every run. If it stops (crash, Ctrl+C, laptop off), run the same
command again: finished runs are skipped. Use --fresh to start over.
"""
import argparse
import csv
import os
from multiprocessing import Pool

# One thread per simulation: parallel runs already use every core, and scikit-learn's OpenMP
# threads fighting over them made traffix runs many times slower. Set before sklearn loads.
os.environ.setdefault("OMP_NUM_THREADS", "1")

import _path  # noqa: F401
from traffix.core import config


def job(args):
    """Runs one simulation. A failure is returned as a row (never raised), so one bad run
    can't stop the batch, and the error message survives the trip back from the worker."""
    import traceback
    from traffix.evaluation.runner import run_one
    try:
        return run_one(*args)
    except Exception as e:
        c, s, seed, _ = args
        return {"controller": c, "scenario": s, "seed": seed,
                "error": f"{e.__class__.__name__}: {e}", "traceback": traceback.format_exc()[-1500:]}


def done_keys(path):
    """Runs already saved in the results file (for resuming)."""
    if not os.path.exists(path):
        return set(), []
    with open(path, newline="") as f:
        rows = [r for r in csv.DictReader(f) if not r.get("error")]
    return {(r["controller"], r["scenario"], int(r["seed"])) for r in rows}, rows


def save(rows, path):
    keys = list(dict.fromkeys(k for r in rows for k in r))
    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


if __name__ == "__main__":
    sim, sc = config.simulation(), config.scenarios()
    p = argparse.ArgumentParser()
    p.add_argument("--controller", nargs="+", default=sim["controllers"], choices=sim["controllers"])
    p.add_argument("--scenario", nargs="+", default=list(sc), choices=list(sc))
    p.add_argument("--seeds", nargs="+", type=int, default=sim["seeds"])
    p.add_argument("--workers", type=int, default=sim["workers"])
    p.add_argument("--gui", action="store_true")
    p.add_argument("--out", default=config.path("results", "results.csv"))
    p.add_argument("--fresh", action="store_true", help="ignore existing results and start over")
    a = p.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    if a.fresh and os.path.exists(a.out):
        os.remove(a.out)
    done, rows = done_keys(a.out)
    jobs = [(c, s, seed, a.gui) for s in a.scenario for c in a.controller for seed in a.seeds
            if (c, s, seed) not in done]
    from traffix.evaluation.runner import GEN, demand_is_current
    stale = sorted({(s, seed) for _, s, seed, _ in jobs
                    if not demand_is_current(os.path.join(GEN, f"{s}_seed{seed}"))})
    if stale:                                               # traffic missing or built for another map
        from traffix.demand.generator import DemandGenerator
        print(f"Building traffic for the {config.network_name()} map ({len(stale)} scenario/seed pairs)")
        gen = DemandGenerator(config.network_files()[0])
        for s, seed in stale:
            gen.build(s, sc[s], seed, GEN)
    if any(c == "fixed_retimed" for c, *_ in jobs):         # build Webster plans once, before workers race
        from traffix.evaluation.retime import build_plan
        for s in sorted({s for c, s, *_ in jobs if c == "fixed_retimed"}):
            build_plan(s, GEN)
    print(f"Running {len(jobs)} simulations" + (f" ({len(done)} already saved in {a.out}, skipped)" if done else ""))
    failures = []
    if a.gui or a.workers <= 1:
        results = map(job, jobs)
    else:
        results = Pool(a.workers).imap(job, jobs)
    for r in results:
        if r.get("error"):
            failures.append(r)
            print(f"{r['scenario']:18s} {r['controller']:14s} seed {r['seed']}: FAILED {r['error']}", flush=True)
            with open(os.path.join(os.path.dirname(a.out), "failed_runs.log"), "a") as f:
                f.write(f"{r['controller']} {r['scenario']} seed {r['seed']}\n{r['traceback']}\n\n")
            continue
        rows.append(r)
        save(rows, a.out)                                   # saved after every run
        print(f"{r['scenario']:18s} {r['controller']:14s} seed {r['seed']}: car wait "
              f"{r['veh_mean_wait_s']:6.1f}s  ped wait {r['ped_mean_wait_s']:6.1f}s  "
              f"unfinished {r['veh_unfinished']:3d}  truncations {r['clearance_truncations']:4d}", flush=True)
    print(f"Saved {len(rows)} runs to {a.out}")
    if failures:
        print(f"{len(failures)} run(s) failed; details in results/failed_runs.log. "
              f"Rerun the same command to retry only those.")
