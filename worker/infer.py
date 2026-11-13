"""Isolated entry point for PUBLIC TotalSegmentator weights only."""
import argparse
import json
import os
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--organs", nargs="+", required=True)
    parser.add_argument("--fast", action="store_true")
    args = parser.parse_args()
    from totalsegmentator.config import setup_totalseg
    setup_totalseg()
    config_path = Path(os.environ["TOTALSEG_HOME_DIR"]) / "config.json"
    config = json.loads(config_path.read_text())
    config["send_usage_stats"] = False
    config_path.write_text(json.dumps(config))
    from totalsegmentator.python_api import totalsegmentator
    totalsegmentator(args.input, args.output, task="total", roi_subset=args.organs,
                    fast=args.fast, device=args.device, nr_thr_resamp=1, nr_thr_saving=1)

if __name__ == "__main__":
    main()
