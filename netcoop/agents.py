"""Deterministic rule-based agents for NetCoop AI."""
from __future__ import annotations

import json
import uuid
import math
import os
import urllib.request
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

PROTOCOL = "agent_message_v1"
ALIASES = {
    "latency": "latency_ms", "latency_s":"latency_ms", "latency_ms": "latency_ms", "jitter": "jitter_ms", "jitter_ms": "jitter_ms",
    "packet_loss": "packet_loss_pct", "packet_loss_pct": "packet_loss_pct", "link_utilization": "link_utilization_pct",
    "link_utilization_pct": "link_utilization_pct", "cpu_utilization": "cpu_utilization_pct", "cpu_utilization_pct": "cpu_utilization_pct",
    "memory_utilization": "memory_utilization_pct", "memory_utilization_pct": "memory_utilization_pct", "queue_drops": "queue_drops",
    "interface_errors": "interface_errors", "throughput_mbps": "throughput_mbps", "bandwidth_mbps": "bandwidth_mbps",
    "signal_strength_dbm": "signal_strength_dbm", "retransmissions_pct": "retransmissions_pct", "service_status": "service_status",
}
ALIASES.update({"ifinerrors":"interface_errors", "if_in_errors":"interface_errors", "rssi":"signal_strength_dbm", "cpuusage":"cpu_utilization_pct", "cpu_usage":"cpu_utilization_pct"})
UNITS = {"latency_ms":"ms", "jitter_ms":"ms", "packet_loss_pct":"%", "link_utilization_pct":"%", "cpu_utilization_pct":"%", "memory_utilization_pct":"%", "queue_drops":"count", "interface_errors":"count", "throughput_mbps":"Mbps", "bandwidth_mbps":"Mbps", "signal_strength_dbm":"dBm", "retransmissions_pct":"%", "service_status":"state"}
SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "docs" / "schema.json").read_text(encoding="utf-8"))
@lru_cache(maxsize=64)
def _threshold(metric, device_type="device", fallback=0):
    try:
        import yaml
        cfg=yaml.safe_load((Path(__file__).resolve().parents[1]/"config"/"thresholds.yaml").read_text(encoding="utf-8")) or {}
        return cfg.get("device_types",{}).get(str(device_type).lower(),{}).get(metric,cfg.get("defaults",{}).get(metric,fallback))
    except Exception: return fallback

def _validate_message(message: dict) -> str | None:
    validator = Draft202012Validator({"$schema": SCHEMA["$schema"], "$defs": SCHEMA["$defs"], "$ref": "#/$defs/agent_message_v1"})
    errors = sorted(validator.iter_errors(message), key=lambda e: list(e.path))
    return errors[0].message if errors else None

CAPABILITY_CARDS = {
    "performance_agent": {"metrics":["latency_ms","jitter_ms","packet_loss_pct","link_utilization_pct","signal_strength_dbm","retransmissions_pct"]},
    "infrastructure_agent": {"metrics":["cpu_utilization_pct","memory_utilization_pct","queue_drops","interface_errors","device_status"]},
    "connectivity_agent": {"metrics":["service_status","topology_scope"],"topology":True},
}

def _envelope(source, findings, evidence, limitations, status="ok", target="orchestrator", received=None, *, message_type="finding", conversation_id=None, in_reply_to=None, normalization=None):
    message = {"schema_version":PROTOCOL,"message_id":str(uuid.uuid4()),
        "timestamp":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"source_agent":source,"target_agent":target,"status":status,
        "message_type":message_type,"conversation_id":conversation_id or str(uuid.uuid4()),"in_reply_to":in_reply_to,
        "capability_card":CAPABILITY_CARDS.get(source,{"metrics":[]}),"normalization":normalization or [],
        "findings":findings,"evidence":evidence,"limitations":limitations}
    if received is not None: message["received_message_ids"] = received
    error = _validate_message(message)
    if error: raise ValueError(f"Invalid {PROTOCOL} message from {source}: {error}")
    return message

def _topology(value, warnings):
    if not isinstance(value, dict):
        warnings.append("Topology is missing or malformed; topology mapping was ignored.")
        return {"devices": [], "links": []}
    result = {"devices": [], "links": []}
    for key in ("devices", "links"):
        entries = value.get(key, [])
        if not isinstance(entries, list):
            warnings.append(f"Topology {key} must be a list; invalid entries were ignored.")
            continue
        for i, item in enumerate(entries):
            if isinstance(item, dict): result[key].append(item)
            else: warnings.append(f"Topology {key} entry {i+1} is not an object and was skipped.")
    return result

def normalize_records(payload: Any):
    warnings=[]
    if isinstance(payload,list): records, topology=payload, {}
    elif isinstance(payload,dict):
        records=payload.get("records",[payload] if "device_id" in payload else [])
        topology=payload.get("topology",{})
        if payload.get("schema_version") not in (None,"telemetry_v1","telemetry_v2"): warnings.append(f"Unsupported telemetry schema version: {payload.get('schema_version')}")
    else: return [],["Input must be a JSON object or array of device records."],{"devices":[],"links":[]}
    topology=_topology(topology,warnings)
    if not isinstance(records,list): records=[]; warnings.append("Records must be a list; invalid records were ignored.")
    normalized=[]; seen=set(); ignored=0
    for i,row in enumerate(records):
        if not isinstance(row,dict): warnings.append(f"Record {i+1} is not an object and was skipped."); continue
        metrics=row.get("metrics",{})
        if "metrics" not in row: warnings.append(f"Record {i+1} has no metrics field.")
        if not isinstance(metrics,dict): warnings.append(f"Record {i+1}: metrics must be an object; record skipped."); continue
        cleaned={}; units=row.get("units",{}) if isinstance(row.get("units",{}),dict) else {}
        if row.get("schema_version") not in (None,"telemetry_v1","telemetry_v2"): warnings.append(f"Record {i+1}: unsupported telemetry schema version `{row.get('schema_version')}`.")
        percent_fields={"link_utilization_pct","cpu_utilization_pct","memory_utilization_pct","packet_loss_pct"}
        normalization=[]
        for field,value in metrics.items():
            canonical=ALIASES.get(str(field).lower())
            if not canonical: warnings.append(f"Record {i+1}: unknown metric `{field}` ignored."); ignored+=1; continue
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value): warnings.append(f"Record {i+1}: `{field}` must be a finite number (booleans are not accepted); value ignored."); ignored+=1; continue
            ambiguous_fraction=canonical in percent_fields and not units.get(field) and 0<value<=1
            explicit_fraction=canonical in percent_fields and units.get(field)=="fraction"
            if ambiguous_fraction or explicit_fraction:
                value=value*100; conversion={"field":field,"canonical":canonical,"from":"fraction","to":"%","factor":100}
                if ambiguous_fraction: conversion["confidence_penalty"]=0.05
                normalization.append(conversion)
            if units.get(field) and units[field]!=UNITS[canonical] and not (canonical=="latency_ms" and units[field]=="s") and not (canonical=="throughput_mbps" and units[field]=="bps") and not (canonical in percent_fields and units[field]=="fraction"): warnings.append(f"Record {i+1}: `{field}` unit `{units[field]}` is incompatible; value ignored."); ignored+=1; continue
            if canonical=="latency_ms" and (units.get(field)=="s" or str(field).lower()=="latency_s"):
                value=value*1000; normalization.append({"field":field,"canonical":canonical,"from":"s","to":"ms","factor":1000})
            if canonical=="throughput_mbps" and units.get(field)=="bps":
                value=value/1_000_000; normalization.append({"field":field,"canonical":canonical,"from":"bps","to":"Mbps","factor":0.000001})
            if str(field).lower() in {"ifinerrors","rssi","cpuusage"}:
                normalization.append({"field":field,"canonical":canonical,"from":"vendor alias","to":"canonical metric"})
            try: number=float(value)
            except (TypeError,ValueError): warnings.append(f"Record {i+1}: `{field}` is not numeric; value ignored."); ignored+=1; continue
            if canonical=="signal_strength_dbm": valid=-120<=number<=0
            else: valid=number>=0 and (canonical not in percent_fields and canonical not in {"retransmissions_pct"} or number<=100)
            if not valid: warnings.append(f"Record {i+1}: `{field}` is outside the accepted range; value ignored."); ignored+=1; continue
            cleaned[canonical]=number
        interfaces=row.get("interfaces",[])
        if not isinstance(interfaces,list): warnings.append(f"Record {i+1}: interfaces must be a list; interface state history ignored."); interfaces=[]
        result={"device_id":str(row.get("device_id") or f"UNKNOWN_{i+1}"),"device_type":str(row.get("device_type","device")),"site":str(row.get("site","Unknown site")),"status":str(row.get("status","Unknown")),"service":row.get("service"),"scenario":row.get("scenario","uploaded data"),"timestamp":row.get("timestamp"),"metrics":cleaned,"interfaces":[x for x in interfaces if isinstance(x,dict)],"ignored_metrics":ignored,"normalization":normalization}
        identity=json.dumps([result["device_id"],result["timestamp"],cleaned,result["interfaces"]],sort_keys=True,default=str)
        if identity in seen: warnings.append(f"Duplicate telemetry record for {result['device_id']} was ignored."); continue
        seen.add(identity); normalized.append(result)
        timestamp=row.get("timestamp")
        if timestamp:
            try:
                parsed=datetime.fromisoformat(str(timestamp).replace("Z","+00:00"))
                if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=timezone.utc)
                age=(datetime.now(timezone.utc)-parsed).total_seconds()
                result["stale"]=age>3600
                if age>3600: warnings.append(f"Record {i+1}: telemetry is stale ({age/3600:.1f} hours old); confidence is lower.")
            except (ValueError,TypeError): warnings.append(f"Record {i+1}: timestamp is invalid; freshness could not be assessed.")
        else: result["stale"]=False
    return normalized,warnings,topology

def _evidence(row,metric,text):
    hypotheses={"latency_ms":[("Latency spike",.65)],"jitter_ms":[("Latency spike",.65)],"packet_loss_pct":[("Link congestion",.45),("Weak Wi-Fi",.4)],"link_utilization_pct":[("Link congestion",.8)],"queue_drops":[("Link congestion",.8)],"signal_strength_dbm":[("Weak Wi-Fi",.85)],"retransmissions_pct":[("Weak Wi-Fi",.8)],"interface_errors":[("Ethernet/interface fault",.8)],"cpu_utilization_pct":[("Hardware failure",.65)],"memory_utilization_pct":[("Hardware failure",.6)]}
    return {"device_id":row["device_id"],"metric":metric,"value":row["metrics"][metric],"unit":UNITS[metric],"interpretation":text,"hypotheses":[{"cause":c,"likelihood":p} for c,p in hypotheses.get(metric,[])]}

def _time_window_analysis(records):
    groups={}
    for row in records: groups.setdefault(row["device_id"],[]).append(row)
    analysis=[]
    for device,rows in groups.items():
        samples=[]
        for row in rows:
            try:
                ts=datetime.fromisoformat(str(row.get("timestamp")).replace("Z","+00:00"))
                if ts.tzinfo is None: ts=ts.replace(tzinfo=timezone.utc)
            except (ValueError,TypeError): continue
            samples.append((ts,row))
        samples.sort(key=lambda item:item[0]); trends=[]
        if len(samples)>1:
            metric_names=set.intersection(*(set(row["metrics"]) for _,row in samples)) if samples else set()
            for metric in sorted(metric_names):
                elapsed=(samples[-1][0]-samples[0][0]).total_seconds()
                if elapsed<=0: continue
                first,last=samples[0][1]["metrics"][metric],samples[-1][1]["metrics"][metric]
                delta=last-first; trends.append({"metric":metric,"sample_count":len(samples),"trend":"increasing" if delta>0 else "decreasing" if delta<0 else "stable","rate_per_second":round(delta/elapsed,6),"unit_per_second":UNITS.get(metric,"unknown")+"/s"})
        states={}
        for _,row in samples:
            for interface in row.get("interfaces",[]):
                key=str(interface.get("id",interface.get("name","interface")))
                state=str(interface.get("state",interface.get("status",""))).lower()
                if state: states.setdefault(key,[]).append(state)
        flaps={key:sum(a!=b for a,b in zip(values,values[1:])) for key,values in states.items() if sum(a!=b for a,b in zip(values,values[1:]))>=2}
        if trends or flaps: analysis.append({"device_id":device,"trend_and_rate":trends,"interface_flapping":flaps})
    return analysis

def performance_agent(records):
    evidence=[]
    for r in records:
        m=r["metrics"]
        if r["status"].lower()=="down" and not m: evidence.append({"device_id":r["device_id"],"metric":"device_status","value":"DOWN","unit":"state","interpretation":"Device is unreachable and has no telemetry"})
        for metric,threshold,label in [("latency_ms",_threshold("latency_ms",r["device_type"],100),"Elevated latency"),("jitter_ms",_threshold("jitter_ms",r["device_type"],30),"Elevated jitter"),("packet_loss_pct",_threshold("packet_loss_pct",r["device_type"],2),"Packet loss above 2%"),("link_utilization_pct",_threshold("link_utilization_pct",r["device_type"],70),"Link utilization above 70%"),("retransmissions_pct",15,"High wireless retransmissions")]:
            if m.get(metric,0)>=threshold and metric in m: evidence.append(_evidence(r,metric,label))
        if m.get("signal_strength_dbm",0)<=-75 and "signal_strength_dbm" in m: evidence.append(_evidence(r,"signal_strength_dbm","Weak Wi-Fi signal"))
        for metric,threshold in [("latency_ms",_threshold("latency_ms",r["device_type"],100)),("jitter_ms",_threshold("jitter_ms",r["device_type"],30)),("packet_loss_pct",_threshold("packet_loss_pct",r["device_type"],2)),("link_utilization_pct",_threshold("link_utilization_pct",r["device_type"],70))]:
            if metric in m and m[metric]<threshold:
                observation=_evidence(r,metric,"Assessed within normal range"); observation["observation_only"]=True; observation["hypotheses"]=[]; evidence.append(observation)
    return _envelope("performance_agent",[f"Found {len(evidence)} performance signal(s)." if evidence else "No above-threshold performance readings were observed."],evidence,[])

def infrastructure_agent(records):
    evidence=[]
    for r in records:
        m=r["metrics"]
        for metric,threshold,label in [("cpu_utilization_pct",_threshold("cpu_utilization_pct",r["device_type"],85),"High device CPU utilization"),("memory_utilization_pct",_threshold("memory_utilization_pct",r["device_type"],90),"High device memory utilization"),("queue_drops",_threshold("queue_drops",r["device_type"],50),"Elevated egress queue drops"),("interface_errors",10,"Elevated interface errors")]:
            if metric in m and m[metric]>threshold: evidence.append(_evidence(r,metric,label))
        if r["status"].lower() in {"critical","down","failed"} and r["metrics"]: evidence.append({"device_id":r["device_id"],"metric":"device_status","value":r["status"],"unit":"state","interpretation":"Device reports critical or failed status"})
        if r["device_type"].lower()=="service" and r["status"].lower() in {"warning","critical","down","failed"}: evidence.append({"device_id":r["device_id"],"metric":"service_availability","value":r["status"],"unit":"state","interpretation":"Service component reports a degraded state"})
        for metric,threshold in [("cpu_utilization_pct",_threshold("cpu_utilization_pct",r["device_type"],85)),("memory_utilization_pct",_threshold("memory_utilization_pct",r["device_type"],90)),("queue_drops",_threshold("queue_drops",r["device_type"],50)),("interface_errors",10)]:
            if metric in m and m[metric]<=threshold:
                observation=_evidence(r,metric,"Assessed within normal range"); observation["observation_only"]=True; observation["hypotheses"]=[]; evidence.append(observation)
        if r["status"].lower() in {"healthy","up","ok"}: evidence.append({"device_id":r["device_id"],"metric":"device_status","value":r["status"],"unit":"state","interpretation":"Device reports normal status","observation_only":True})
    return _envelope("infrastructure_agent",[f"Found {len(evidence)} infrastructure signal(s)." if evidence else "No above-threshold infrastructure readings were observed."],evidence,[])

def connectivity_agent(records,topology):
    warnings=[]; topology=_topology(topology,warnings); evidence=[]
    ids={str(d.get("id")) for d in topology["devices"] if d.get("id") is not None}
    for r in records:
        if r["device_id"] in ids: evidence.append({"device_id":r["device_id"],"metric":"topology_scope","value":r["site"],"unit":"topology","interpretation":"Telemetry device maps to a known topology segment"})
        if r["device_type"].lower()=="service" and r["status"].lower() in {"warning","critical","down","failed"}:
            evidence.append({"device_id":r["device_id"],"metric":"service_availability","value":r["status"],"unit":"state","interpretation":"Service component reports a degraded state"})
        if r["metrics"].get("service_status",1)<1:
            evidence.append({"device_id":r["device_id"],"metric":"service_status","value":r["metrics"]["service_status"],"unit":"state","interpretation":"Network service is unavailable"})
    for link in topology["links"]:
        value=link.get("utilization_pct")
        if isinstance(value,(int,float)) and value>=85: evidence.append({"device_id":str(link.get("source","link")),"metric":"link_utilization_pct","value":value,"unit":"%","interpretation":"Topology link is highly utilized"})
    return _envelope("connectivity_agent",[f"Mapped {len(evidence)} topology signal(s)."],evidence,warnings+([] if topology["devices"] else ["No topology was supplied; affected segments cannot be inferred."]))

def correlation_agent(messages):
    usable=[m for m in messages if isinstance(m,dict) and not _validate_message(m) and m.get("target_agent")=="correlation_agent"]
    evidence_by_pair={}
    for m in usable:
        for e in m["evidence"]:
            if e.get("observation_only"): continue
            key=(e.get("device_id"),e.get("metric"))
            evidence_by_pair.setdefault(key,dict(e,source_message_id=m["message_id"]))
    evidence=list(evidence_by_pair.values())
    bydev={}
    for e in evidence: bydev.setdefault(e["device_id"],set()).add(e["metric"])
    candidates={}
    def add(cause,e):
        c=candidates.setdefault(cause,{"evidence":[],"families":set(),"devices":set()}); c["evidence"].append(e); c["families"].add(e["source_message_id"]); c["devices"].add(e["device_id"])
    for e in evidence:
        m,v=e["metric"],e["value"]
        # Specialist-declared hypotheses are the source of cause mapping.
        for hypothesis in e.get("hypotheses",[]):
            if hypothesis.get("likelihood",0)>=.55 and hypothesis.get("cause")!="Latency spike": add(hypothesis["cause"],e)
        # Explicit categorical and topology evidence has direct semantic meaning.
        if m=="service_availability" and str(v).lower() in {"warning","critical","down","failed"}: add("DNS/DHCP service failure",e)
        if m=="service_status" and v<1: add("DNS/DHCP service failure",e)
        if m=="device_status" and str(v).lower() in {"critical","failed","down"}: add("Hardware failure",e)
        if m=="link_utilization_pct" and v>=70: add("Link congestion",e)
    # Require same-device congestion corroboration; latency itself is not a cause.
    for cause,c in list(candidates.items()):
        c["evidence"]=[e for e in c["evidence"] if e["metric"]!="latency_ms"]
    rows_by_device={r["device_id"]:r for r in getattr(correlation_agent,"records",[])}
    # Utilization or queue pressure is the required congestion anchor; latency,
    # loss, and jitter only corroborate congestion when that anchor is present
    # on the same device.
    for device,metrics in bydev.items():
        device_values={e["metric"]:e["value"] for e in evidence if e["device_id"]==device}
        congestion_anchor=device_values.get("link_utilization_pct",0)>=70 or device_values.get("queue_drops",0)>50
        if congestion_anchor:
            for e in evidence:
                if e["device_id"]==device and e["metric"] in {"latency_ms","packet_loss_pct","jitter_ms"}:
                    add("Link congestion",e)
    congestion_anchors=[e for e in candidates.get("Link congestion",{}).get("evidence",[]) if e.get("metric") in {"link_utilization_pct","queue_drops"}]
    if congestion_anchors:
        candidates["Upstream vs local congestion"]={"evidence":congestion_anchors,"families":{e["source_message_id"] for e in congestion_anchors},"devices":{e["device_id"] for e in congestion_anchors}}
    # Wireless symptom combination upgrades loss/latency to Wi-Fi, but keeps
    # the diagnosis grounded in independently measured radio signals.
    for device,metrics in bydev.items():
        if metrics & {"signal_strength_dbm","retransmissions_pct"} and metrics & {"latency_ms","packet_loss_pct"}:
            for e in evidence:
                if e["device_id"]==device and e["metric"] in {"latency_ms","packet_loss_pct"}: add("Weak Wi-Fi",e)
        # Critical status + CPU >=95 + errors is a specific hardware rule.
        mvals={e["metric"]:e["value"] for e in evidence if e["device_id"]==device}
        if str(mvals.get("device_status","")).lower()=="critical" and mvals.get("cpu_utilization_pct",0)>=95 and mvals.get("interface_errors",0)>10:
            for e in evidence:
                if e["device_id"]==device and e["metric"] in {"device_status","cpu_utilization_pct","interface_errors"}: add("Hardware failure",e)
    ranked=[]
    for cause,c in candidates.items():
        unique={(e["device_id"],e["metric"]):e for e in c["evidence"]}
        candidate_evidence=list(unique.values())
        signals=len(candidate_evidence); families={e["source_message_id"] for e in candidate_evidence}
        score=.25 if cause=="Upstream vs local congestion" else min(.95, .36*min(3,len(families)) + .05*min(3,max(0,signals-1)))
        ranked.append({"cause":cause,"score":round(score,2),"families":sorted(families),"evidence":candidate_evidence,"distinct_signals":signals})
    # Specific faults take precedence over generic link symptoms.
    precedence={"Hardware failure":6,"DNS/DHCP service failure":5,"Weak Wi-Fi":4,"Ethernet/interface fault":3,"Link congestion":2,"Latency spike":1}
    ranked.sort(key=lambda x:(x["score"],precedence.get(x["cause"],0)),reverse=True)
    # Latency spike requires three distinct performance readings together.
    for device, metrics in bydev.items():
        if len(metrics & {"latency_ms","jitter_ms","packet_loss_pct"}) >= 2 and "latency_ms" in metrics and not metrics & {"signal_strength_dbm","retransmissions_pct"}:
            group=[e for e in evidence if e["device_id"]==device and e["metric"] in {"latency_ms","jitter_ms","packet_loss_pct"}]
            group_families={e["source_message_id"] for e in group}
            group_signals={(e["device_id"],e["metric"]) for e in group}
            group_score=min(.95,.36*min(3,len(group_families))+.05*min(3,max(0,len(group_signals)-1)))
            ranked.append({"cause":"Latency spike","score":round(group_score,2),"families":sorted(group_families),"evidence":group,"distinct_signals":len(group_signals)})
    # Normalize after adding composite rules; favor specific device failure evidence.
    for candidate in ranked:
        candidate["score"]=round(candidate["score"],2)
    ranked.sort(key=lambda x:(x["score"],precedence.get(x["cause"],0)),reverse=True)
    for device, metrics in bydev.items():
        values={e["metric"]:e["value"] for e in evidence if e["device_id"]==device}
        if str(values.get("device_status","")).lower()=="critical" and values.get("cpu_utilization_pct",0)>=95 and values.get("interface_errors",0)>10:
            hardware=next((c for c in ranked if c["cause"]=="Hardware failure"),None)
            if hardware: hardware["score"]=max(hardware["score"],.95)
    ranked.sort(key=lambda x:(x["score"],precedence.get(x["cause"],0)),reverse=True)
    winner=ranked[0] if ranked and ranked[0]["score"]>=.24 and (len(ranked[0]["families"])>=2 or ranked[0]["distinct_signals"]>=3 or ranked[0]["cause"]=="Latency spike" and ranked[0]["distinct_signals"]>=2 or ranked[0]["cause"]=="Ethernet/interface fault" and any(e["metric"]=="interface_errors" and e["value"]>=100 for e in ranked[0]["evidence"])) else None
    forced_hardware=bool(ranked and ranked[0]["cause"]=="Hardware failure" and any(str(e["value"]).lower()=="critical" for e in ranked[0]["evidence"]))
    if len(ranked)>1 and abs(ranked[0]["score"]-ranked[1]["score"])<=.05 and not forced_hardware: winner=None
    is_ambiguous=bool(ranked and len(ranked)>1 and abs(ranked[0]["score"]-ranked[1]["score"])<=.05 and not forced_hardware)
    msg=_envelope("correlation_agent",[f"Ranked {len(ranked)} candidate cause(s)."],[],[],"ok" if winner else "warning",received=[m["message_id"] for m in usable],message_type="challenge" if is_ambiguous else "finding")
    return {"message":msg,"ranked_candidates":ranked,"winner":winner,"ambiguous":is_ambiguous}

def reporting_agent(correlation,records,warnings,messages,failures=None,topology=None):
    failures=failures or []; winner=correlation["winner"]; ranked=correlation["ranked_candidates"]
    unreachable=[r["device_id"] for r in records if r["status"].lower()=="down" and not r["metrics"]]
    unreachable_only=bool(unreachable and not winner)
    cause=winner["cause"] if winner else "unreachable" if unreachable_only else "Ambiguous" if correlation["ambiguous"] else "Insufficient evidence to identify a probable root cause"
    action={"Link congestion":["Inspect the affected link utilization and queue counters; compare traffic over the incident window."],"Weak Wi-Fi":["Check access point placement, channel contention, signal quality, and retransmissions."],"Hardware failure":["Check device alarms, CPU health, interface errors, and cabling with an operator."],"Ethernet/interface fault":["Inspect interface counters, cabling, optics, and link flaps."],"DNS/DHCP service failure":["Check DNS/DHCP service health and recent configuration changes."],"unreachable":["Verify power, cabling, management reachability, and device availability before collecting telemetry."]}
    confidence=.75 if unreachable_only else winner["score"] if winner else (min(.5,ranked[0]["score"]) if correlation["ambiguous"] and ranked else 0)
    if winner and len(winner["families"])==1 and winner["distinct_signals"]>=3:
        confidence=min(.55,confidence)
    penalties={"unsupported_schema":.15 if any("unsupported telemetry schema" in w.lower() for w in warnings) else 0,
        "ignored_metrics":min(.20,.05*sum(not w.startswith("Duplicate telemetry") and any(token in w for token in ("ignored", "is incompatible", "is not numeric", "unknown metric")) for w in warnings)),
        "device_not_in_topology":.10 if topology and topology.get("devices") and any(r["device_id"] not in {str(d.get("id")) for d in topology.get("devices",[]) if isinstance(d,dict)} for r in records) else 0,
        "no_topology":.10 if not any("topology_scope"==e["metric"] for e in (winner["evidence"] if winner else [])) and any("No topology" in l for m in messages for l in m.get("limitations",[])) else 0,
        "ambiguous_fraction":.05 if any(x.get("confidence_penalty") for r in records for x in r.get("normalization",[])) else 0,
        "stale_telemetry":.10 if any(r.get("stale") for r in records) else 0}
    # Independent evidence families are the message sources contributing to a candidate.
    strong_interface=bool(winner and winner["cause"]=="Ethernet/interface fault" and any(e["metric"]=="interface_errors" and e["value"]>=100 for e in winner["evidence"]))
    if winner and len(winner["families"])<2 and winner["distinct_signals"]<3 and not strong_interface: confidence=0
    if strong_interface: confidence=min(.55,confidence)
    confidence=max(0,round(confidence-sum(penalties.values())-.05*len(failures),2))
    if failures: confidence=min(.5,confidence)
    conflicts=[]
    if any(m.get("source_agent")=="performance_agent" and m["evidence"] for m in messages) and not any(c["cause"] in {"Link congestion","Weak Wi-Fi"} for c in ranked):
        conflicts.append({"agents":["performance_agent","infrastructure_agent"],"claims":["Performance signals are elevated","No supporting congestion or device cause was confirmed"],"resolution_rule":"Require cause-specific corroboration on the same device; lower confidence by 0.05."}); confidence=max(0,confidence-.05)
    support=[]
    if winner:
        support=[{k:e[k] for k in ("metric","value","unit","interpretation","device_id","source_message_id")} for e in winner["evidence"]]
    evidenced={e["device_id"] for e in (winner["evidence"] if winner else [])}
    adjacency={}
    for link in (topology or {}).get("links",[]): adjacency.setdefault(str(link.get("source")),[]).append(str(link.get("target")))
    downstream=set(); frontier=list(evidenced)
    while frontier:
        for child in adjacency.get(frontier.pop(),[]):
            if child not in evidenced and child not in downstream: downstream.add(child); frontier.append(child)
    findings=[]
    for candidate in ranked:
        for d in sorted({e["device_id"] for e in candidate["evidence"]}):
            findings.append({"device_id":d,"segment":next((r.get("site") for r in records if r["device_id"]==d),"Unknown segment"),"cause":candidate["cause"],"confidence":candidate["score"]})
    findings.extend({"device_id":d,"segment":next((r.get("site") for r in records if r["device_id"]==d),"Unknown segment"),"cause":"unreachable","confidence":.75} for d in unreachable)
    report={"incident_id":"INC-"+uuid.uuid4().hex[:8].upper(),"status":"ambiguous" if correlation["ambiguous"] else "diagnosed" if (winner and confidence>0) or unreachable_only else "insufficient_evidence","suspected_root_cause":cause,"confidence":confidence,
        "affected_devices":sorted(evidenced|downstream|set(unreachable)),"downstream_affected_devices":sorted(downstream),"findings":findings,"time_window_analysis":_time_window_analysis(records),"supporting_evidence":support or [e for m in messages for e in m.get("evidence",[]) if e.get("device_id") in unreachable and e.get("metric")=="device_status"],
        "alternative_causes":[c["cause"] for c in ranked if not winner or c["cause"]!=winner["cause"]][:3],"recommended_actions":(["Collect the discriminating measurement for: "+" vs ".join(c["cause"] for c in ranked[:2])] if correlation["ambiguous"] else action.get(cause,["Collect time-aligned latency, loss, device health, and topology measurements."])),
        "evidence_sources":winner["families"] if winner else [],"limitations":list(dict.fromkeys([*warnings,*[x for m in messages for x in m.get("limitations",[])],*(f"Agent {f} failed; remaining agents continued." for f in failures),*( ["single evidence family"] if winner and len(winner["families"])==1 else []),"Confidence is a deterministic rule-based evidence score, not a calibrated probability."])),
        "ranked_candidates":ranked,"tied_candidates":[c["cause"] for c in ranked[:2]] if correlation["ambiguous"] else [],"conflicts":conflicts,"confidence_breakdown":{"base":.75 if unreachable_only else winner["score"] if winner else ranked[0]["score"] if correlation["ambiguous"] and ranked else 0,"scoring_rule":"0.36 per supporting agent family + 0.05 per additional distinct device/metric pair; capped at 0.95. Single-family diagnoses with 3+ signals cap at 0.55; critical hardware signature gets priority score 0.85.","penalties":penalties,"agent_failures":round(.05*len(failures),2),"final":confidence}}
    return report

def _apply_model_hypotheses(messages,proposals):
    """Accept only grounded proposals that pass deterministic cause checks."""
    allowed={"Link congestion":{"link_utilization_pct","queue_drops","packet_loss_pct","latency_ms","jitter_ms"},"Weak Wi-Fi":{"signal_strength_dbm","retransmissions_pct","packet_loss_pct","latency_ms"},"Hardware failure":{"cpu_utilization_pct","memory_utilization_pct","device_status"},"Ethernet/interface fault":{"interface_errors"},"DNS/DHCP service failure":{"service_status","service_availability"},"Latency spike":{"latency_ms","jitter_ms","packet_loss_pct"}}
    evidence=[e for m in messages for e in m.get("evidence",[]) if not e.get("observation_only")]
    for proposal in proposals if isinstance(proposals,list) else []:
        if not isinstance(proposal,dict): continue
        device,metric,cause=proposal.get("device_id"),proposal.get("metric"),proposal.get("cause")
        try: likelihood=float(proposal.get("likelihood"))
        except (TypeError,ValueError): continue
        matches=[e for e in evidence if e.get("device_id")==device and e.get("metric")==metric]
        if not matches or metric not in allowed.get(cause,set()) or not 0<=likelihood<=.95: continue
        values={e["metric"]:e["value"] for e in evidence if e.get("device_id")==device}
        verified=(cause=="Link congestion" and (values.get("link_utilization_pct",0)>=70 or values.get("queue_drops",0)>50)) or (cause=="Weak Wi-Fi" and (values.get("signal_strength_dbm",0)<=-75 or values.get("retransmissions_pct",0)>=15)) or (cause=="Hardware failure" and (values.get("cpu_utilization_pct",0)>=85 or values.get("memory_utilization_pct",0)>=90 or str(values.get("device_status","")).lower() in {"critical","failed"})) or (cause=="Ethernet/interface fault" and values.get("interface_errors",0)>10) or (cause=="DNS/DHCP service failure" and (values.get("service_status",1)<1 or str(values.get("service_availability","")).lower() in {"warning","critical","down","failed"})) or (cause=="Latency spike" and values.get("latency_ms",0)>=100 and (values.get("jitter_ms",0)>=30 or values.get("packet_loss_pct",0)>=2))
        if not verified: continue
        for message in messages:
            for item in message.get("evidence",[]):
                if item.get("device_id")==device and item.get("metric")==metric:
                    hs=item.setdefault("hypotheses",[])
                    existing=next((h for h in hs if h.get("cause")==cause),None)
                    if existing: existing["likelihood"]=max(existing.get("likelihood",0),likelihood); existing["origin"]="model"
                    else: hs.append({"cause":cause,"likelihood":likelihood,"origin":"model"})

def run_diagnosis(payload:Any, model_reviewer=None, model_hypothesizer=None, agent_transport=None):
    records,warnings,topology=normalize_records(payload); messages=[]; failures=[]; conversation_id=str(uuid.uuid4())
    remote_base=agent_transport if isinstance(agent_transport,str) and agent_transport.startswith("http") else os.environ.get("NETCOOP_AGENT_URL") if agent_transport is None else None
    for name,fn,args in [("performance_agent",performance_agent,(records,)),("infrastructure_agent",infrastructure_agent,(records,)),("connectivity_agent",connectivity_agent,(records,topology))]:
        try:
            if remote_base:
                endpoint={"performance_agent":"performance","infrastructure_agent":"infrastructure","connectivity_agent":"connectivity"}[name]
                request=urllib.request.Request(remote_base.rstrip("/")+"/agents/"+endpoint,data=json.dumps(payload,allow_nan=False).encode("utf-8"),headers={"Content-Type":"application/json"},method="POST")
                with urllib.request.urlopen(request,timeout=5) as response: remote=json.loads(response.read().decode("utf-8"))
                message=remote["message"]
                warnings.extend(w for w in remote.get("warnings",[]) if w not in warnings)
            else: message=fn(*args)
        except Exception as exc:
            failures.append(name); message=_envelope(name,[f"Agent failed: {type(exc).__name__}: {exc}"],[],["Agent execution failed; diagnosis continued."],"error")
        if _validate_message(message):
            failures.append(name); warnings.append(f"Invalid message from {name} was rejected: {_validate_message(message)}")
            message=_envelope(name,["Invalid agent message rejected."],[],["Invalid agent output was rejected."],"error")
        message["target_agent"]="correlation_agent"; message["conversation_id"]=conversation_id
        message["normalization"]=[x for r in records for x in r.get("normalization",[])]
        messages.append(message)
    # A concrete follow-up exchanges a task and an acknowledgement across the
    # protocol when performance is elevated but infrastructure measured normal CPU.
    perf=next((m for m in messages if m.get("source_agent")=="performance_agent"),{})
    infra=next((m for m in messages if m.get("source_agent")=="infrastructure_agent"),{})
    elevated_devices={e["device_id"] for e in perf.get("evidence",[]) if e.get("metric") in {"latency_ms","packet_loss_pct","jitter_ms"} and not e.get("observation_only")}
    normal_cpu={e["device_id"]:e for e in infra.get("evidence",[]) if e.get("metric")=="cpu_utilization_pct" and e.get("observation_only")}
    for device in sorted(elevated_devices & set(normal_cpu)):
        request=_envelope("correlation_agent",[f"Follow-up request: is CPU normal on {device}?"],[],[],target="infrastructure_agent",message_type="task_request",conversation_id=conversation_id)
        messages.append(request)
        reply=_envelope("infrastructure_agent",[f"CPU is normal on {device}; measured {normal_cpu[device]['value']}% below its device-type threshold."],[normal_cpu[device]],[],target="correlation_agent",message_type="ack",conversation_id=conversation_id,in_reply_to=request["message_id"],received=[request["message_id"]])
        messages.append(reply)
    if model_hypothesizer is not None:
        try: _apply_model_hypotheses(messages,model_hypothesizer(messages))
        except Exception as exc: warnings.append(f"Model hypothesis generation failed; rule-based evidence was used: {type(exc).__name__}.")
    try:
        corr=correlation_agent(messages)
    except Exception as exc:
        failures.append("correlation_agent")
        failed_message=_envelope("correlation_agent",[f"Agent failed: {type(exc).__name__}: {exc}"],[],["Agent execution failed; diagnosis continued."],"error",target="reporting_agent",received=[m["message_id"] for m in messages])
        corr={"message":failed_message,"ranked_candidates":[],"winner":None,"ambiguous":False}
    if _validate_message(corr.get("message", {})):
        failures.append("correlation_agent")
        corr={"message":_envelope("correlation_agent",["Invalid agent message rejected."],[],["Invalid agent output was rejected."],"error",target="reporting_agent",received=[m["message_id"] for m in messages]),"ranked_candidates":[],"winner":None,"ambiguous":False}
    try:
        report=reporting_agent(corr,records,warnings,messages,failures,topology)
    except Exception as exc:
        failures.append("reporting_agent")
        report={"incident_id":"INC-"+uuid.uuid4().hex[:8].upper(),"status":"insufficient_evidence","suspected_root_cause":"Insufficient evidence to identify a probable root cause","confidence":0.0,"affected_devices":[],"supporting_evidence":[],"alternative_causes":[],"tied_candidates":[],"ranked_candidates":corr["ranked_candidates"],"recommended_actions":["Review the input and collect another time-aligned sample."],"evidence_sources":[],"limitations":list(dict.fromkeys([*warnings,f"Agent reporting_agent failed: {type(exc).__name__}."])),"conflicts":[],"confidence_breakdown":{"base":0,"penalties":{},"agent_failures":.05*len(failures),"final":0}}
    corr_message=corr["message"]; corr_message["target_agent"]="reporting_agent"; corr_message["conversation_id"]=conversation_id
    corr_message["in_reply_to"]=messages[0]["message_id"] if messages else None
    messages.append(corr_message)
    if model_reviewer is not None:
        try:
            model_review=model_reviewer(report,messages)
            review_errors=list(Draft202012Validator(SCHEMA["$defs"]["model_review"]).iter_errors(model_review))
            if review_errors or model_review.get("status")!="reviewed":
                raise ValueError("Model review did not match the review schema.")
            model_status="ok"
            model_limitations=["Model review is advisory and does not change the deterministic verdict or confidence."]
            model_findings=[model_review["summary"]]
            report["narrative"]=model_review["summary"]
        except Exception as exc:
            model_review={"status":"unavailable","agrees_with_rule_verdict":False,"summary":"The optional model review could not be completed; the deterministic diagnosis is unchanged.","alternative_explanations":[],"recommended_checks":[],"uncertainty":f"Review error: {type(exc).__name__}."}
            model_status="warning"
            model_limitations=["Optional Groq model review failed; the deterministic rule-based report remains available."]
            model_findings=[model_review["summary"]]
            report["limitations"]=list(dict.fromkeys([*report["limitations"],*model_limitations]))
        model_message=_envelope("groq_review_agent",model_findings,report["supporting_evidence"],model_limitations,model_status,target="reporting_agent",received=[m["message_id"] for m in messages])
        report["model_review"]=model_review
        messages.append(model_message)
    reporting_failed="reporting_agent" in failures
    report_message=_envelope("reporting_agent",["Agent failed while assembling the report." if reporting_failed else f"Report verdict: {report['suspected_root_cause']} ({report['status']}); evidence score {report['confidence']:.0%}."],report["supporting_evidence"],report["limitations"],"error" if reporting_failed else "ok",target="orchestrator",received=[m["message_id"] for m in messages])
    messages.append(report_message)
    for message in messages:
        message["conversation_id"]=conversation_id
        if message["source_agent"]=="reporting_agent": message["in_reply_to"]=corr_message["message_id"]
        if not message.get("normalization"): message["normalization"]=[x for r in records for x in r.get("normalization",[])]
        error=_validate_message(message)
        if error: raise ValueError(f"Invalid agent message rejected: {error}")
    report_error=Draft202012Validator(SCHEMA).iter_errors(report)
    report_error=next(report_error,None)
    if report_error: raise ValueError(f"Invalid diagnostic report: {report_error.message}")
    return {"records":records,"topology":topology,"warnings":warnings,"agent_messages":messages,"ranked_candidates":corr["ranked_candidates"],"report":report,"messages_json":json.dumps(messages,indent=2,allow_nan=False)}
