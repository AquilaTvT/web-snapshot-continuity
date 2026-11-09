"""Rebuild temporal constructions and model curves without network access."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.temporal import (return_obstruction, common_times, all_k_subsets_coexist,
                         noncoexistence_certificate, verify_noncoexistence, bridge_error)


def write_csv(name, rows):
    path = ROOT / 'data/derived' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    temporal = []
    for n in range(2, 13):
        family, window = return_obstruction(n)
        certificate = noncoexistence_certificate(family, window)
        temporal.append(dict(
            n=n,
            all_proper_coexist=int(all_k_subsets_coexist(family, window, n - 1)),
            global_coexists=int(bool(common_times(family, window))),
            certificate_segments=len(certificate),
            verified=int(verify_noncoexistence(family, window, certificate))))
    write_csv('temporal_obstructions.csv', temporal)
    # Twelve significant digits: libm implementations differ in the last
    # bit of exp/expm1, and the curve should rebuild byte for byte anywhere.
    bridge = [dict(rate_duration=i / 20,
                   conditional_error=format(bridge_error(i / 20, 1, .5), '.12g'))
              for i in range(101)]
    write_csv('bridge_model.csv', bridge)
    print(json.dumps({
        'temporal_obstruction_rows': len(temporal),
        'bridge_model_rows': len(bridge),
        'scope': 'Mathematical constructions and a specified model curve; not empirical incidence.'
    }, indent=2))


if __name__ == '__main__':
    main()
