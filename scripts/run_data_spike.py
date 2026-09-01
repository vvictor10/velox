from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from velox_spikes.data_spike import run_data_spike, write_data_spike_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tickers", nargs="*", default=["AAPL", "MSFT", "GOOGL"])
    args = parser.parse_args()
    results = run_data_spike(args.tickers)
    write_data_spike_report(results)
    print("Wrote data spike results to docs/local/spikes/data_spike_results.md")


if __name__ == "__main__":
    main()
