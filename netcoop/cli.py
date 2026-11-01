"""Command line interface for NetCoop diagnostics."""
import argparse, json
from pathlib import Path
from .agents import run_diagnosis

def main():
    parser=argparse.ArgumentParser(prog="python -m netcoop diagnose")
    sub=parser.add_subparsers(dest="command",required=True)
    diagnose=sub.add_parser("diagnose"); diagnose.add_argument("file"); diagnose.add_argument("--format",choices=["json","md"],default="json")
    args=parser.parse_args(); payload=json.loads(Path(args.file).read_text(encoding="utf-8")); report=run_diagnosis(payload)["report"]
    if args.format=="json": print(json.dumps(report,indent=2,allow_nan=False))
    else:
        print(f"# {report['suspected_root_cause']}\n\n- Status: {report['status']}\n- Confidence: {report['confidence']:.0%}\n- Affected devices: {', '.join(report['affected_devices']) or 'None'}\n")
        print("## Evidence\n")
        for e in report["supporting_evidence"]: print(f"- {e['device_id']} · {e['metric']}: {e['value']} {e['unit']} — {e['interpretation']}")
if __name__=="__main__": main()
