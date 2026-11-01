"""Command line interface for NetCoop diagnostics."""
import argparse, json
from datetime import datetime
from pathlib import Path
from .agents import run_diagnosis

def main():
    parser=argparse.ArgumentParser(prog="python -m netcoop diagnose")
    sub=parser.add_subparsers(dest="command",required=True)
    diagnose=sub.add_parser("diagnose"); diagnose.add_argument("file"); diagnose.add_argument("--format",choices=["json","md"],default="json")
    diagnose.add_argument("--as-of", help="ISO 8601 reference time for stale-reading checks")
    diagnose.add_argument("--seed", default="0", help="Seed used with --deterministic-ids")
    diagnose.add_argument("--deterministic-ids", action="store_true", help="Make IDs and message timestamps repeatable")
    args=parser.parse_args(); payload=json.loads(Path(args.file).read_text(encoding="utf-8"))
    as_of=datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else None
    report=run_diagnosis(payload,as_of=as_of,seed=args.seed,deterministic_ids=args.deterministic_ids)["report"]
    if args.format=="json": print(json.dumps(report,indent=2,allow_nan=False))
    else:
        print(f"# {report['suspected_root_cause']}\n\n- Status: {report['status']}\n- Confidence: {report['confidence']:.0%}\n- Affected devices: {', '.join(report['affected_devices']) or 'None'}\n")
        print("## Evidence\n")
        for e in report["supporting_evidence"]: print(f"- {e['device_id']} · {e['metric']}: {e['value']} {e['unit']} — {e['interpretation']}")
if __name__=="__main__": main()
