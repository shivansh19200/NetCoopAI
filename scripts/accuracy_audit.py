"""Repeatable 1,000-case randomized confusion-matrix and confidence audit."""
from collections import defaultdict
import random
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from netcoop.agents import run_diagnosis
from netcoop.data_generator import generate_fuzz_case
import json

SEED=20261101
LABELS=["normal","Link congestion","Weak Wi-Fi","Hardware failure","Ethernet/interface fault","DNS/DHCP service failure"]

def main():
    rng=random.Random(SEED); matrix={truth:{pred:0 for pred in LABELS+['other']} for truth in LABELS}; scores=defaultdict(lambda:[0,0]); fuzz_errors=0
    for _ in range(1000):
        row,truth=generate_fuzz_case(rng)
        # Fuzz adversarial values independently of the randomized valid signal generator.
        if rng.random()<.12:
            row['metrics'][rng.choice(list(row['metrics']))]=rng.choice([True,float('inf'),float('nan'),"broken"])
        try:
            result=run_diagnosis({"records":[row]})
            report=result['report']
            pred=report['suspected_root_cause'] if report['status'] in {'diagnosed', 'low_confidence'} else 'normal' if report['status']=='healthy' else 'other'
            if pred not in matrix[truth]: pred='other'
            matrix[truth][pred]+=1
            confidence=report['confidence']; bucket=min(9,int(confidence*10)); scores[bucket][0]+=1; scores[bucket][1]+=int(pred==truth)
        except Exception:
            fuzz_errors+=1; matrix[truth]['other']+=1
    labels=LABELS+['other']; lines=[f"# Randomized accuracy audit (seed {SEED}, n=1000)","", "Truth is the generated primary fault. Twenty percent of cases receive a distinct second fault; a normal baseline with an injected fault is labeled by that fault. A low-confidence report still predicts its named cause; `other` means the system abstained or returned an ambiguous result, so this strict single-label matrix does not credit every correct alternative in a multi-fault report.","", "## Confusion matrix (rows = expected, columns = predicted)","", "| Expected \\ Predicted | "+" | ".join(labels)+" |", "|---|"+"---|"*len(labels)]
    for truth in LABELS: lines.append("| "+truth+" | "+" | ".join(str(matrix[truth][p]) for p in labels)+" |")
    lines += ["",f"Fuzz exceptions: {fuzz_errors}","", "## Empirical confidence calibration by score decile", "", "Correctness is exact single-label agreement, including abstentions in the lowest bin. These are empirical reliability measurements on this generated distribution, not production probabilities; no in-sample adjustment is applied to runtime scores.","", "| Score bin | Cases | Correct | Observed accuracy |", "|---|---:|---:|---:|"]
    for b in range(10):
        n,correct=scores[b]; lines.append(f"| {b/10:.1f}–{(b+1)/10:.1f} | {n} | {correct} | {correct/n:.1%}" if n else f"| {b/10:.1f}–{(b+1)/10:.1f} | 0 | 0 | —")
    fixture_path=Path(__file__).resolve().parents[1]/"data"/"sample_telemetry.json"
    fixture=json.loads(fixture_path.read_text(encoding="utf-8"))
    scenario_names=list(dict.fromkeys(row.get("scenario", "unknown") for row in fixture.get("records", [])))
    lines += ["", "## Current nine-scenario demo results", "", "These fixed fixtures are evaluated separately from the randomized audit. Confidence is the displayed deterministic evidence score.", "", "| Scenario | Status | Cause | Confidence |", "|---|---|---|---:|"]
    for scenario in scenario_names:
        rows=[row for row in fixture["records"] if row.get("scenario")==scenario]
        report=run_diagnosis({"fixture":True,"records":rows,"topology":fixture.get("topology",{})},deterministic_ids=True)["report"]
        lines.append(f"| {scenario} | {report['status']} | {report['suspected_root_cause']} | {report['confidence']:.0%} |")
    target=Path(__file__).resolve().parents[1]/"docs"/"ACCURACY.md"; target.write_text("\n".join(lines)+"\n",encoding="utf-8")
    if hasattr(sys.stdout,"reconfigure"): sys.stdout.reconfigure(encoding="utf-8",errors="replace")
    print("\n".join(lines))

if __name__=="__main__": main()
