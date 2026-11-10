# Bus-First evidence: 10 paired seeds on Tunis J1..J6 (SUMO 1.28, 10 Nov 2026)

Simulation only, synthetic demand. Occupancy is assumed (car 1.2, bus 50). Fuel and CO2 are SUMO/HBEFA proxies.
Full paired tests with 95% CIs and Holm correction: `python scripts/analyze.py` writes `results/bus_first.md`.

Reproduce: `python scripts/run_experiments.py --scenario morning_peak evening_peak heavy incident emergency bus_disruption --controller fixed fixed_retimed actuated traffix_rules traffix traffix_bus_first --seeds 1 2 3 4 5 6 7 8 9 10`

## Findings

1. **Safety is the only clear win.** TraffiX controllers cut car greens started while people are on the crossing by 92 to 96% against every baseline in every scenario (Holm p < 0.0001).
2. **No flow or energy gain is supported.** Against SUMO actuated, traffix is clearly worse in bus_disruption (delay per person +18%, fuel per person-km +7%) and in emergency (car wait +88%). All other traffix comparisons: no clear difference.
3. **traffix_bus_first (bus_weight 10) does not help.** Against traffix it is within noise on delay per person; against actuated it is worse (delay per person +11 to +32%, significant in 5 of 6 scenarios).
4. **The signals are not the bottleneck on this map.** Webster critical flow ratios at J1..J6 are 0.04 to 0.16, so Webster picks near-minimum cycles and `fixed_retimed` does not beat the default 90 s plan. Delay comes mostly from unsignalised side streets and the grid (README section 14). Better signal timing alone cannot remove it.
5. **Buses lose about 10 minutes per trip** (bus time loss 440 to 790 s) against 46 to 173 s mean car wait, so person-weighted delay is dominated by buses. The lever for bus riders is likely bus lanes or the yield junctions, not the six light plans.

## Means over 10 seeds

### morning_peak

| controller | delay/person (s) | bus time loss (s) | car wait (s) | ped wait (s) | fuel g/person-km | greens on walkers |
|---|---|---|---|---|---|---|
| fixed | 466.4 | 622.3 | 96.4 | 130.6 | 61.8 | 278.0 |
| fixed_retimed | 510.1 | 678.7 | 114.9 | 135.3 | 64.9 | 299.0 |
| actuated | 451.7 | 602.2 | 92.0 | 135.4 | 61.0 | 389.2 |
| traffix_rules | 534.4 | 713.0 | 122.8 | 131.4 | 66.0 | 19.0 |
| traffix | 518.1 | 692.1 | 115.4 | 128.3 | 64.8 | 15.5 |
| traffix_bus_first | 499.9 | 666.6 | 112.2 | 149.7 | 63.9 | 17.6 |

### evening_peak

| controller | delay/person (s) | bus time loss (s) | car wait (s) | ped wait (s) | fuel g/person-km | greens on walkers |
|---|---|---|---|---|---|---|
| fixed | 399.5 | 526.5 | 79.8 | 133.1 | 57.7 | 271.4 |
| fixed_retimed | 432.2 | 572.9 | 85.5 | 123.3 | 59.1 | 282.0 |
| actuated | 387.5 | 518.2 | 61.6 | 118.6 | 55.5 | 385.4 |
| traffix_rules | 450.1 | 594.8 | 95.7 | 116.2 | 60.4 | 15.7 |
| traffix | 469.2 | 620.8 | 102.1 | 120.9 | 61.4 | 16.8 |
| traffix_bus_first | 446.4 | 590.4 | 94.7 | 116.1 | 60.2 | 17.1 |

### heavy

| controller | delay/person (s) | bus time loss (s) | car wait (s) | ped wait (s) | fuel g/person-km | greens on walkers |
|---|---|---|---|---|---|---|
| fixed | 588.0 | 794.7 | 165.1 | 147.8 | 76.9 | 322.1 |
| fixed_retimed | 572.9 | 772.5 | 160.6 | 129.7 | 76.2 | 327.5 |
| actuated | 543.3 | 743.7 | 133.7 | 148.2 | 72.2 | 444.7 |
| traffix_rules | 563.6 | 763.8 | 152.4 | 137.7 | 74.7 | 22.4 |
| traffix | 580.3 | 779.1 | 173.1 | 142.7 | 78.0 | 25.3 |
| traffix_bus_first | 582.4 | 792.8 | 154.9 | 154.7 | 75.2 | 22.8 |

### incident

| controller | delay/person (s) | bus time loss (s) | car wait (s) | ped wait (s) | fuel g/person-km | greens on walkers |
|---|---|---|---|---|---|---|
| fixed | 426.7 | 564.5 | 84.3 | 116.7 | 59.4 | 274.1 |
| fixed_retimed | 502.7 | 669.3 | 105.7 | 128.2 | 63.1 | 282.8 |
| actuated | 423.2 | 565.1 | 76.2 | 120.7 | 58.2 | 391.7 |
| traffix_rules | 486.9 | 652.4 | 97.5 | 130.9 | 61.9 | 17.0 |
| traffix | 476.1 | 632.4 | 101.0 | 127.4 | 61.9 | 19.8 |
| traffix_bus_first | 489.0 | 655.4 | 95.3 | 137.7 | 61.5 | 16.3 |

### emergency

| controller | delay/person (s) | bus time loss (s) | car wait (s) | ped wait (s) | fuel g/person-km | greens on walkers |
|---|---|---|---|---|---|---|
| fixed | 375.6 | 478.6 | 71.4 | 113.0 | 52.4 | 223.2 |
| fixed_retimed | 370.7 | 473.6 | 66.3 | 108.3 | 51.8 | 241.0 |
| actuated | 340.5 | 439.4 | 46.3 | 101.8 | 49.3 | 326.3 |
| traffix_rules | 401.2 | 517.6 | 68.1 | 114.1 | 52.5 | 14.9 |
| traffix | 426.9 | 546.3 | 87.2 | 109.4 | 54.9 | 14.6 |
| traffix_bus_first | 403.4 | 522.0 | 66.9 | 118.7 | 52.3 | 13.3 |

### bus_disruption

| controller | delay/person (s) | bus time loss (s) | car wait (s) | ped wait (s) | fuel g/person-km | greens on walkers |
|---|---|---|---|---|---|---|
| fixed | 440.7 | 587.4 | 92.2 | 121.8 | 61.6 | 262.1 |
| fixed_retimed | 509.1 | 674.8 | 125.0 | 126.6 | 66.9 | 276.8 |
| actuated | 419.1 | 562.2 | 78.6 | 123.4 | 59.6 | 379.1 |
| traffix_rules | 515.3 | 690.5 | 115.6 | 125.4 | 65.6 | 18.2 |
| traffix | 494.7 | 664.0 | 104.2 | 131.9 | 63.9 | 18.2 |
| traffix_bus_first | 552.7 | 738.1 | 137.3 | 135.2 | 69.2 | 16.5 |
