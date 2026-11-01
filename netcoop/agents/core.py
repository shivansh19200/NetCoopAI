"""Deterministic rule-based agents for NetCoop AI."""
from __future__ import annotations

import json
import copy
import uuid
import math
import os
import urllib.request
import contextvars
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from ..scoring import candidate_score, cause_priority, setting, threshold as _configured_threshold

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
SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "docs" / "schema.json").read_text(encoding="utf-8"))
MESSAGE_VALIDATOR = Draft202012Validator({"$schema": SCHEMA["$schema"], "$defs": SCHEMA["$defs"], "$ref": "#/$defs/agent_message_v1"})
REPORT_VALIDATOR = Draft202012Validator(SCHEMA)
MODEL_REVIEW_VALIDATOR = Draft202012Validator(SCHEMA["$defs"]["model_review"])
MESSAGE_FAST_SCHEMA = copy.deepcopy(MESSAGE_VALIDATOR.schema)
MESSAGE_FAST_SCHEMA["$defs"]["agent_message_v1"]["properties"]["evidence"] = {"type": "array"}
MESSAGE_FAST_VALIDATOR = Draft202012Validator(MESSAGE_FAST_SCHEMA)
REPORT_FAST_SCHEMA = copy.deepcopy(SCHEMA)
REPORT_FAST_SCHEMA["$defs"]["evidence"] = {"type": "object"}
REPORT_FAST_VALIDATOR = Draft202012Validator(REPORT_FAST_SCHEMA)
_ID_CONTEXT = contextvars.ContextVar("netcoop_id_context", default=None)


@lru_cache(maxsize=64)
def _threshold(metric, device_type="device", fallback=0):
    """Compatibility wrapper for device-specific threshold lookup."""
    return _configured_threshold(metric, device_type, fallback)

def _validate_message(message: dict) -> str | None:
    """Validate envelope structure and efficiently check large evidence batches."""
    evidence = message.get("evidence", [])
    if isinstance(evidence, list) and len(evidence) > 100:
        errors = MESSAGE_FAST_VALIDATOR.iter_errors(message)
        error = next(errors, None)
        if error:
            return error.message
        for item in evidence:
            if (not isinstance(item, dict)
                    or not all(key in item for key in ("device_id", "metric", "value", "unit", "interpretation"))
                    or not isinstance(item["device_id"], str)
                    or not isinstance(item["metric"], str)
                    or not isinstance(item["unit"], str)
                    or not isinstance(item["interpretation"], str)):
                return "Large evidence batch contains a malformed evidence item."
            for hypothesis in item.get("hypotheses", []):
                likelihood = hypothesis.get("likelihood") if isinstance(hypothesis, dict) else None
                if (not isinstance(hypothesis, dict) or not isinstance(hypothesis.get("cause"), str)
                        or isinstance(likelihood, bool) or not isinstance(likelihood, (int, float))
                        or not 0 <= likelihood <= 1):
                    return "Large evidence batch contains a malformed hypothesis."
        return None
    errors = sorted(MESSAGE_VALIDATOR.iter_errors(message), key=lambda e: list(e.path))
    return errors[0].message if errors else None


def _validate_report(report: dict) -> str | None:
    """Validate large reports with a cached lightweight evidence definition."""
    errors = REPORT_FAST_VALIDATOR.iter_errors(report)
    error = next(errors, None)
    return error.message if error else None


def _new_id(kind: str, content: Any = None) -> str:
    """Create a unique ID, or a repeatable UUID5 inside deterministic runs."""
    context = _ID_CONTEXT.get()
    if context is None or not context["deterministic"]:
        return str(uuid.uuid4())
    seed, counter = context["seed"], context["counter"]
    context["counter"] += 1
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"netcoop:{seed}:{kind}:{counter}:{canonical}"))


def _message_time() -> datetime:
    """Use a stable message timestamp in deterministic mode."""
    context = _ID_CONTEXT.get()
    if context and context["deterministic"]:
        return context["timestamp"]
    return datetime.now(timezone.utc)

CAPABILITY_CARDS = {
    "performance_agent": {"metrics":["latency_ms","jitter_ms","packet_loss_pct","link_utilization_pct","signal_strength_dbm","retransmissions_pct"]},
    "infrastructure_agent": {"metrics":["cpu_utilization_pct","memory_utilization_pct","queue_drops","interface_errors","device_status"]},
    "connectivity_agent": {"metrics":["service_status","topology_scope"],"topology":True},
}

def _envelope(source, findings, evidence, limitations, status="ok", target="orchestrator", received=None, *, message_type="finding", conversation_id=None, in_reply_to=None, normalization=None):
    id_content = {"source": source, "target": target, "findings": findings, "evidence": evidence}
    message = {"schema_version":PROTOCOL,"message_id":_new_id("message", id_content),
        "timestamp":_message_time().isoformat().replace("+00:00","Z"),"source_agent":source,"target_agent":target,"status":status,
        "message_type":message_type,"conversation_id":conversation_id or _new_id("conversation", id_content),"in_reply_to":in_reply_to,
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


def _cap_warnings(warnings: list[str], limit: int = 50) -> list[str]:
    """Keep diagnostics readable when an input has many bad rows."""
    if len(warnings) <= limit:
        return warnings
    duplicate_warnings = [warning for warning in warnings if "duplicate record" in warning.lower()]
    ordinary = [warning for warning in warnings if "duplicate record" not in warning.lower()]
    kept_duplicate = duplicate_warnings[:1]
    slots = limit - 1 - len(kept_duplicate)
    omitted = len(warnings) - min(slots, len(ordinary)) - len(kept_duplicate)
    return [*ordinary[:slots], *kept_duplicate, f"+{omitted} more warning(s) omitted."]

def normalize_records(payload: Any, as_of: datetime | None = None):
    """Normalize telemetry without guessing units or treating fixture time as stale."""
    warnings=[]
    fixture = False
    if isinstance(payload,list): records, topology=payload, {}
    elif isinstance(payload,dict):
        records=payload.get("records",[payload] if "device_id" in payload else [])
        topology=payload.get("topology",{})
        fixture = payload.get("fixture") is True
        if payload.get("schema_version") not in (None,"telemetry_v1","telemetry_v2"): warnings.append(f"Unsupported telemetry schema version: {payload.get('schema_version')}")
    else: return [],["Input must be a JSON object or array of device records."],{"devices":[],"links":[]}
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    topology=_topology(topology,warnings)
    if not isinstance(records,list): records=[]; warnings.append("Records must be a list; invalid records were ignored.")
    normalized=[]; seen=set(); seen_input=set(); ignored=0; freshest_by_device={}; duplicate_count=0
    for i,row in enumerate(records):
        if not isinstance(row,dict): warnings.append(f"Record {i+1} is not an object and was skipped."); continue
        input_identity=json.dumps(row,sort_keys=True,default=str)
        if input_identity in seen_input:
            duplicate_count+=1
            continue
        seen_input.add(input_identity)
        metrics=row.get("metrics",{})
        if "metrics" not in row: warnings.append(f"Record {i+1} has no metrics field.")
        if not isinstance(metrics,dict): warnings.append(f"Record {i+1}: metrics must be an object; record skipped."); continue
        cleaned={}; raw_units=row.get("units",{}) if isinstance(row.get("units",{}),dict) else {}
        units={str(key).strip().lower():str(value).strip().lower() for key,value in raw_units.items()}
        if row.get("schema_version") not in (None,"telemetry_v1","telemetry_v2"): warnings.append(f"Record {i+1}: unsupported telemetry schema version `{row.get('schema_version')}`.")
        percent_fields={"link_utilization_pct","cpu_utilization_pct","memory_utilization_pct","packet_loss_pct"}
        percent_values=[]
        for name,value in metrics.items():
            canonical=ALIASES.get(str(name).strip().lower())
            if canonical in percent_fields and isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value):
                percent_values.append((str(name).strip().lower(),canonical,value,units.get(str(name).strip().lower())))
        explicit_fraction_hint=any(unit=="fraction" and value<=1 for _,_,value,unit in percent_values)
        infer_fraction=bool(percent_values) and explicit_fraction_hint and all(0<=value<=1 for _,_,value,_ in percent_values)
        if infer_fraction and any(unit is None for _,_,_,unit in percent_values):
            warnings.append(f"Record {i+1}: other unitless percentage fields were treated as fractions based on an explicit fraction unit; confidence is lower.")
        normalization=[]
        for field,value in metrics.items():
            field_key=str(field).strip().lower()
            canonical=ALIASES.get(field_key)
            if not canonical: warnings.append(f"Record {i+1}: unknown metric `{field}` ignored."); ignored+=1; continue
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value): warnings.append(f"Record {i+1}: `{field}` must be a finite number (booleans are not accepted); value ignored."); ignored+=1; continue
            unit=units.get(field_key)
            explicit_fraction=canonical in percent_fields and unit=="fraction"
            inferred_fraction=canonical in percent_fields and unit is None and infer_fraction
            if explicit_fraction or inferred_fraction:
                value=value*100; conversion={"field":field,"canonical":canonical,"from":"fraction","to":"%","factor":100}
                if inferred_fraction: conversion["confidence_penalty"]=0.05
                normalization.append(conversion)
            if unit and unit!=UNITS[canonical] and not (canonical=="latency_ms" and unit=="s") and not (canonical=="throughput_mbps" and unit=="bps") and not (canonical in percent_fields and unit=="fraction"):
                warnings.append(f"Record {i+1}: `{field}` unit `{raw_units.get(field, unit)}` is incompatible; value ignored."); ignored+=1; continue
            if canonical=="latency_ms" and (unit=="s" or field_key=="latency_s"):
                value=value*1000; normalization.append({"field":field,"canonical":canonical,"from":"s","to":"ms","factor":1000})
            elif field_key=="latency" and unit is None and 0<value<1:
                warnings.append(f"Record {i+1}: unitless `latency` value {value:g} looks like seconds; label it with unit `s` to convert it safely.")
            if canonical=="throughput_mbps" and unit=="bps":
                value=value/1_000_000; normalization.append({"field":field,"canonical":canonical,"from":"bps","to":"Mbps","divide_by":1_000_000})
            if field_key in {"ifinerrors","rssi","cpuusage"}:
                normalization.append({"field":field,"canonical":canonical,"from":"vendor alias","to":"canonical metric"})
            try: number=float(value)
            except (TypeError,ValueError): warnings.append(f"Record {i+1}: `{field}` is not numeric; value ignored."); ignored+=1; continue
            if canonical=="signal_strength_dbm": valid=-120<=number<=0
            else: valid=number>=0 and (canonical not in percent_fields and canonical not in {"retransmissions_pct"} or number<=100)
            if not valid: warnings.append(f"Record {i+1}: `{field}` is outside the accepted range; value ignored."); ignored+=1; continue
            cleaned[canonical]=number
        interfaces=row.get("interfaces",[])
        if not isinstance(interfaces,list): warnings.append(f"Record {i+1}: interfaces must be a list; interface state history ignored."); interfaces=[]
        result={"device_id":str(row.get("device_id") or f"UNKNOWN_{i+1}"),"device_type":str(row.get("device_type","device")),"site":str(row.get("site","Unknown site")),"status":str(row.get("status","Unknown")),"service":row.get("service"),"scenario":row.get("scenario","uploaded data"),"timestamp":row.get("timestamp"),"metrics":cleaned,"interfaces":[x for x in interfaces if isinstance(x,dict)],"ignored_metrics":ignored,"normalization":normalization,"fixture":fixture or row.get("fixture") is True}
        identity=json.dumps([result["device_id"],result["timestamp"],cleaned,result["interfaces"]],sort_keys=True,default=str)
        if identity in seen: duplicate_count+=1; continue
        seen.add(identity); normalized.append(result)
        timestamp=row.get("timestamp")
        if timestamp:
            try:
                parsed=datetime.fromisoformat(str(timestamp).replace("Z","+00:00"))
                if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=timezone.utc)
                age=(as_of-parsed).total_seconds()
                result["stale"]=age>3600 and not result["fixture"]
                current=freshest_by_device.get(result["device_id"])
                if current is None or parsed>current[0]: freshest_by_device[result["device_id"]]=(parsed,age,i+1,result["fixture"])
            except (ValueError,TypeError): warnings.append(f"Record {i+1}: timestamp is invalid; freshness could not be assessed.")
        else: result["stale"]=False
    # Older samples in a trend are expected. Freshness is judged from the most
    # recent reading for each device, while individual historical rows retain
    # their own `stale` annotation for display/debugging.
    if duplicate_count:
        warnings.append(f"{duplicate_count} duplicate record(s) ignored.")
    stale_devices={device for device,(_,age,_,is_fixture) in freshest_by_device.items() if age>3600 and not is_fixture}
    for device in stale_devices:
        _,age,index,_=freshest_by_device[device]
        warnings.append(f"Record {index}: latest telemetry for {device} is stale ({age/3600:.1f} hours old); confidence is lower.")
    for row in normalized:
        row["latest_telemetry_stale"]=row["device_id"] in stale_devices and not row["fixture"]
    return normalized,_cap_warnings(warnings),topology

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
                delta=last-first; trends.append({"metric":metric,"sample_count":len(samples),"trend":"increasing" if delta>0 else "decreasing" if delta<0 else "stable","rate_per_second":delta/elapsed,"unit_per_second":UNITS.get(metric,"unknown")+"/s"})
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
        for metric,threshold,label in [("latency_ms",_threshold("latency_ms",r["device_type"],100),"Elevated latency"),("jitter_ms",_threshold("jitter_ms",r["device_type"],30),"Elevated jitter"),("packet_loss_pct",_threshold("packet_loss_pct",r["device_type"],2),"Packet loss above 2%"),("link_utilization_pct",_threshold("link_utilization_pct",r["device_type"],70),"Link utilization above 70%"),("retransmissions_pct",_threshold("retransmissions_pct",r["device_type"],15),"High wireless retransmissions")]:
            if m.get(metric,0)>=threshold and metric in m: evidence.append(_evidence(r,metric,label))
        if m.get("signal_strength_dbm",0)<=_threshold("signal_strength_dbm",r["device_type"],-75) and "signal_strength_dbm" in m: evidence.append(_evidence(r,"signal_strength_dbm","Weak Wi-Fi signal"))
        for metric,threshold in [("latency_ms",_threshold("latency_ms",r["device_type"],100)),("jitter_ms",_threshold("jitter_ms",r["device_type"],30)),("packet_loss_pct",_threshold("packet_loss_pct",r["device_type"],2)),("link_utilization_pct",_threshold("link_utilization_pct",r["device_type"],70))]:
            if metric in m and m[metric]<threshold:
                observation=_evidence(r,metric,"Assessed within normal range"); observation["observation_only"]=True; observation["hypotheses"]=[]; evidence.append(observation)
    return _envelope("performance_agent",[f"Found {len(evidence)} performance signal(s)." if evidence else "No above-threshold performance readings were observed."],evidence,[])

def infrastructure_agent(records):
    evidence=[]
    for r in records:
        m=r["metrics"]
        for metric,threshold,label in [("cpu_utilization_pct",_threshold("cpu_utilization_pct",r["device_type"],85),"High device CPU utilization"),("memory_utilization_pct",_threshold("memory_utilization_pct",r["device_type"],90),"High device memory utilization"),("queue_drops",_threshold("queue_drops",r["device_type"],50),"Elevated egress queue drops"),("interface_errors",_threshold("interface_errors",r["device_type"],10),"Elevated interface errors")]:
            if metric in m and m[metric]>threshold: evidence.append(_evidence(r,metric,label))
        if r["status"].lower() in {"critical","down","failed"} and r["metrics"]: evidence.append({"device_id":r["device_id"],"metric":"device_status","value":r["status"],"unit":"state","interpretation":"Device reports critical or failed status"})
        if r["device_type"].lower()=="service" and r["status"].lower() in {"warning","critical","down","failed"}: evidence.append({"device_id":r["device_id"],"metric":"service_availability","value":r["status"],"unit":"state","interpretation":"Service component reports a degraded state"})
        for metric,threshold in [("cpu_utilization_pct",_threshold("cpu_utilization_pct",r["device_type"],85)),("memory_utilization_pct",_threshold("memory_utilization_pct",r["device_type"],90)),("queue_drops",_threshold("queue_drops",r["device_type"],50)),("interface_errors",_threshold("interface_errors",r["device_type"],10))]:
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
        if isinstance(value,(int,float)) and value>=_threshold("connectivity_link_high_pct","device",85): evidence.append({"device_id":str(link.get("source","link")),"metric":"link_utilization_pct","value":value,"unit":"%","interpretation":"Topology link is highly utilized"})
    return _envelope("connectivity_agent",[f"Mapped {len(evidence)} topology signal(s)."],evidence,warnings+([] if topology["devices"] else ["No topology was supplied; affected segments cannot be inferred."]))

def correlation_agent(messages, records=None):
    """Rank likely causes from independent agent families per device."""
    usable = [message for message in messages if isinstance(message, dict)
              and not _validate_message(message) and message.get("target_agent") == "correlation_agent"]
    evidence_by_pair = {}
    for message in usable:
        for item in message["evidence"]:
            if item.get("observation_only"):
                continue
            key = (item.get("device_id"), item.get("metric"))
            evidence_by_pair.setdefault(key, dict(item, evidence_family=message["source_agent"], source_message_id=message["message_id"]))

    by_device = {}
    for item in evidence_by_pair.values():
        by_device.setdefault(item["device_id"], []).append(item)
    device_types = {row["device_id"]: row.get("device_type", "device") for row in (records or [])}
    candidates = {}

    def add(cause, item):
        bucket = candidates.setdefault((cause, item["device_id"]), {"evidence": {}, "families": set()})
        bucket["evidence"][(item["device_id"], item["metric"])] = item
        bucket["families"].add(item["evidence_family"])

    for device, items in by_device.items():
        values = {item["metric"]: item["value"] for item in items}
        metrics = set(values)
        device_type = device_types.get(device, "device")
        link_limit = _threshold("congestion_link_anchor_pct", device_type, 70)
        queue_limit = _threshold("congestion_queue_anchor", device_type, 50)
        cpu_signature = _threshold("hardware_signature_cpu_pct", device_type, 95)
        by_metric = {item["metric"]: item for item in items}

        for item in items:
            metric, value = item["metric"], item["value"]
            for hypothesis in item.get("hypotheses", []):
                if hypothesis.get("likelihood", 0) >= 0.55 and hypothesis.get("cause") != "Latency spike":
                    add(hypothesis["cause"], item)
            if metric == "service_availability" and str(value).lower() in {"warning", "critical", "down", "failed"}:
                add("DNS/DHCP service failure", item)
            elif metric == "service_status" and value < 1:
                add("DNS/DHCP service failure", item)
            elif metric == "device_status" and str(value).lower() in {"critical", "failed", "down"}:
                add("Hardware failure", item)
            elif metric == "link_utilization_pct" and value >= link_limit:
                add("Link congestion", item)
            elif metric == "interface_errors" and value > _threshold("interface_errors", device_type, 10):
                add("Ethernet/interface fault", item)

        congestion_anchor = values.get("link_utilization_pct", 0) >= link_limit or values.get("queue_drops", 0) > queue_limit
        if congestion_anchor:
            for metric in ("link_utilization_pct", "queue_drops", "latency_ms", "packet_loss_pct", "jitter_ms"):
                if metric in by_metric:
                    add("Link congestion", by_metric[metric])
            for metric in ("link_utilization_pct", "queue_drops"):
                if metric in by_metric:
                    add("Upstream vs local congestion", by_metric[metric])

        wireless = metrics & {"signal_strength_dbm", "retransmissions_pct"}
        if wireless and metrics & {"latency_ms", "packet_loss_pct"}:
            for metric in ("signal_strength_dbm", "retransmissions_pct", "latency_ms", "packet_loss_pct"):
                if metric in by_metric:
                    add("Weak Wi-Fi", by_metric[metric])

        if (str(values.get("device_status", "")).lower() == "critical"
                and values.get("cpu_utilization_pct", 0) >= cpu_signature
                and values.get("interface_errors", 0) > _threshold("interface_errors", device_type, 10)):
            for metric in ("device_status", "cpu_utilization_pct", "interface_errors"):
                if metric in by_metric:
                    add("Hardware failure", by_metric[metric])

        if ("latency_ms" in metrics and len(metrics & {"latency_ms", "jitter_ms", "packet_loss_pct"}) >= 2
                and not wireless):
            for metric in ("latency_ms", "jitter_ms", "packet_loss_pct"):
                if metric in by_metric:
                    add("Latency spike", by_metric[metric])

    ranked = []
    for (cause, device_id), bucket in candidates.items():
        candidate_evidence = list(bucket["evidence"].values())
        families = bucket["families"]
        signals = len(candidate_evidence)
        score = 0.25 if cause == "Upstream vs local congestion" else candidate_score(len(families), signals)
        device_values = {item["metric"]: item["value"] for item in by_device.get(device_id, [])}
        hardware_signature = (
            str(device_values.get("device_status", "")).lower() == "critical"
            and device_values.get("cpu_utilization_pct", 0) >= _threshold("hardware_signature_cpu_pct", "device", 95)
            and device_values.get("interface_errors", 0) > _threshold("interface_errors", "device", 10)
        )
        if cause == "Hardware failure" and hardware_signature:
            score = max(score, setting("scoring.hardware_signature_priority", 0.95))
        rank_score = score
        if cause == "Hardware failure" and hardware_signature:
            rank_score += 0.001
        ranked.append({"cause": cause, "device_id": device_id, "score": score, "rank_score": rank_score,
                       "families": sorted(families), "evidence": candidate_evidence,
                       "distinct_signals": signals})

    ranked.sort(key=lambda item: (item["rank_score"], cause_priority(item["cause"])), reverse=True)
    minimum = _threshold("diagnosis_minimum_score", "device", 0.24)
    by_device_ranked = {}
    for candidate in ranked:
        by_device_ranked.setdefault(candidate["device_id"], []).append(candidate)
    device_results = {}
    for device_id, options in by_device_ranked.items():
        qualifying = [candidate for candidate in options if candidate["score"] >= minimum and (
            len(candidate["families"]) >= 2 or candidate["distinct_signals"] >= 3
            or candidate["cause"] == "Latency spike" and candidate["distinct_signals"] >= 2
            or candidate["cause"] == "Ethernet/interface fault" and any(
                item["metric"] == "interface_errors" and item["value"] >= 100 for item in candidate["evidence"]
            )
        )]
        first = qualifying[0] if qualifying else None
        forced_hardware = bool(first and first["cause"] == "Hardware failure"
                               and first["score"] >= setting("scoring.hardware_signature_priority", 0.95))
        is_ambiguous = len(qualifying) > 1 and abs(first["score"] - qualifying[1]["score"]) <= setting(
            "scoring.ambiguous_tie_margin", 0.05
        ) + 1e-9 and not forced_hardware
        device_results[device_id] = {"ranked_candidates": options,
                                     "winner": first if first and not is_ambiguous else None,
                                     "ambiguous": is_ambiguous}
    ambiguous = any(result["ambiguous"] for result in device_results.values())
    winners = [result["winner"] for result in device_results.values() if result["winner"]]
    winner = max(winners, key=lambda item: (item["rank_score"], cause_priority(item["cause"]))) if winners else None
    message = _envelope("correlation_agent", [f"Ranked {len(ranked)} possible causes."], [], [],
                        "ok" if winner else "warning", received=[item["message_id"] for item in usable],
                        message_type="challenge" if ambiguous else "finding")
    for candidate in ranked:
        candidate.pop("rank_score", None)
    return {"message": message, "ranked_candidates": ranked, "winner": winner,
            "ambiguous": ambiguous, "device_results": device_results}

def reporting_agent(correlation,records,warnings,messages,failures=None,topology=None):
    failures=failures or []; winner=correlation["winner"]; ranked=correlation["ranked_candidates"]
    unreachable=[r["device_id"] for r in records if r["status"].lower()=="down" and not r["metrics"]]
    unreachable_only=bool(unreachable and not winner)
    normal_evidence = [item for message in messages for item in message.get("evidence", []) if item.get("observation_only")]
    normal_pairs = {(item.get("device_id"), item.get("metric")) for item in normal_evidence}
    healthy_statuses = {"healthy", "up", "ok"}
    has_abnormal_reading = any(
        not item.get("observation_only") and item.get("metric") != "topology_scope"
        for message in messages for item in message.get("evidence", [])
    )
    healthy = bool(records) and all(row["status"].lower() in healthy_statuses for row in records) and not has_abnormal_reading and not winner and not correlation["ambiguous"]
    cause=winner["cause"] if winner else "No fault detected" if healthy else "unreachable" if unreachable_only else "Ambiguous" if correlation["ambiguous"] else "Insufficient evidence to identify a probable root cause"
    action={"Link congestion":["Inspect the affected link utilization and queue counters; compare traffic over the incident window."],"Weak Wi-Fi":["Check access point placement, channel contention, signal quality, and retransmissions."],"Hardware failure":["Check device alarms, CPU health, interface errors, and cabling with an operator."],"Ethernet/interface fault":["Inspect interface counters, cabling, optics, and link flaps."],"DNS/DHCP service failure":["Check DNS/DHCP service health and recent configuration changes."],"unreachable":["Verify power, cabling, management reachability, and device availability before collecting telemetry."]}
    healthy_base = min(.95, .50 + .10 * min(5, len(normal_pairs)))
    confidence=healthy_base if healthy else .75 if unreachable_only else winner["score"] if winner else (min(.5,ranked[0]["score"]) if correlation["ambiguous"] and ranked else 0)
    if winner and winner["cause"] != "Hardware failure" and len(winner["families"])==1 and winner["distinct_signals"]>=3:
        confidence=min(setting("scoring.single_family_cap",.55),confidence)
    penalties={"unsupported_schema":.15 if any("unsupported telemetry schema" in w.lower() for w in warnings) else 0,
        "ignored_metrics":min(.20,.05*sum("duplicate record" not in w.lower() and any(token in w for token in ("ignored", "is incompatible", "is not numeric", "unknown metric")) for w in warnings)),
        "device_not_in_topology":.10 if topology and topology.get("devices") and any(r["device_id"] not in {str(d.get("id")) for d in topology.get("devices",[]) if isinstance(d,dict)} for r in records) else 0,
        "no_topology":.10 if not healthy and not any("topology_scope"==e["metric"] for e in (winner["evidence"] if winner else [])) and any("No topology" in l for m in messages for l in m.get("limitations",[])) else 0,
        "ambiguous_fraction":.05 if any(x.get("confidence_penalty") for r in records for x in r.get("normalization",[])) else 0,
        "stale_telemetry":setting("defaults.stale_penalty",.10) if any(r.get("latest_telemetry_stale") for r in records) else 0}
    # Independent evidence families are the message sources contributing to a candidate.
    strong_interface=bool(winner and winner["cause"]=="Ethernet/interface fault" and any(e["metric"]=="interface_errors" and e["value"]>=100 for e in winner["evidence"]))
    if winner and len(winner["families"])<2 and winner["distinct_signals"]<3 and not strong_interface: confidence=0
    if strong_interface: confidence=min(setting("scoring.single_family_cap",.55),confidence)
    confidence=max(0,confidence-sum(penalties.values())-.05*len(failures))
    if failures: confidence=min(.5,confidence)
    conflicts=[]
    if any(m.get("source_agent")=="performance_agent" and m["evidence"] for m in messages) and not any(c["cause"] in {"Link congestion","Weak Wi-Fi"} for c in ranked):
        conflicts.append({"agents":["performance_agent","infrastructure_agent"],"claims":["Performance signals are elevated","No supporting congestion or device cause was confirmed"],"resolution_rule":"Require cause-specific corroboration on the same device; lower confidence by 0.05."}); confidence=max(0,confidence-.05)
    support=[]
    if winner:
        support=[{k:e[k] for k in ("metric","value","unit","interpretation","device_id","source_message_id")} for e in winner["evidence"]]
    elif healthy:
        for message in messages:
            support.extend(dict(item, source_message_id=message["message_id"])
                           for item in message.get("evidence", []) if item.get("observation_only"))
    evidenced={e["device_id"] for e in (winner["evidence"] if winner else [])}
    adjacency={}
    for link in (topology or {}).get("links",[]): adjacency.setdefault(str(link.get("source")),[]).append(str(link.get("target")))
    downstream=set(); frontier=list(evidenced)
    while frontier:
        for child in adjacency.get(frontier.pop(),[]):
            if child not in evidenced and child not in downstream: downstream.add(child); frontier.append(child)
    segment_by_device={row["device_id"]:row.get("site","Unknown segment") for row in records}
    findings=[]
    for candidate in ranked:
        for d in sorted({e["device_id"] for e in candidate["evidence"]}):
            findings.append({"device_id":d,"segment":segment_by_device.get(d,"Unknown segment"),"cause":candidate["cause"],"confidence":candidate["score"]})
    findings.extend({"device_id":d,"segment":segment_by_device.get(d,"Unknown segment"),"cause":"unreachable","confidence":.75} for d in unreachable)
    status = "healthy" if healthy else "ambiguous" if correlation["ambiguous"] else "diagnosed" if ((winner and confidence>=.3) or unreachable_only) else "low_confidence" if winner else "insufficient_evidence"
    report={"incident_id":"INC-"+_new_id("incident", {"cause":cause,"devices":sorted(evidenced|downstream|set(unreachable))})[:8].upper(),"status":status,"suspected_root_cause":cause,"confidence":confidence,
        "affected_devices":sorted(evidenced|downstream|set(unreachable)),"downstream_affected_devices":sorted(downstream),"findings":findings,"time_window_analysis":_time_window_analysis(records),"supporting_evidence":support or [e for m in messages for e in m.get("evidence",[]) if e.get("device_id") in unreachable and e.get("metric")=="device_status"],
        "alternative_causes":[c["cause"] for c in ranked if not winner or c["cause"]!=winner["cause"]][:3],"recommended_actions":["No action needed; continue routine monitoring."] if healthy else (["Collect the discriminating measurement for: "+" vs ".join(c["cause"] for c in ranked[:2])] if correlation["ambiguous"] else action.get(cause,["Collect time-aligned latency, loss, device health, and topology measurements."])),
        "evidence_sources":winner["families"] if winner else [],"limitations":list(dict.fromkeys([*warnings,*[x for m in messages for x in m.get("limitations",[])],*(f"Agent {f} failed; remaining agents continued." for f in failures),*( ["single evidence family"] if winner and len(winner["families"])==1 else []),"Confidence is a deterministic rule-based evidence score, not a calibrated probability."])),
        "ranked_candidates":ranked,"tied_candidates":[c["cause"] for c in ranked[:2]] if correlation["ambiguous"] else [],"conflicts":conflicts,"confidence_breakdown":{"base":healthy_base if healthy else .75 if unreachable_only else winner["score"] if winner else ranked[0]["score"] if correlation["ambiguous"] and ranked else 0,"scoring_rule":"0.36 per independent agent family + 0.05 per additional distinct device/metric; maximum 0.95. One-family diagnoses with 3+ signals cap at 0.55. Critical hardware signatures receive 0.95 priority.","penalties":penalties,"agent_failures":.05*len(failures),"final":confidence}}
    return report

def _apply_model_hypotheses(messages,proposals):
    """Accept only grounded proposals that pass deterministic cause checks."""
    allowed={"Link congestion":{"link_utilization_pct","queue_drops","packet_loss_pct","latency_ms","jitter_ms"},"Weak Wi-Fi":{"signal_strength_dbm","retransmissions_pct","packet_loss_pct","latency_ms"},"Hardware failure":{"cpu_utilization_pct","memory_utilization_pct","device_status"},"Ethernet/interface fault":{"interface_errors"},"DNS/DHCP service failure":{"service_status","service_availability"},"Latency spike":{"latency_ms","jitter_ms","packet_loss_pct"}}
    evidence_by_pair={}
    values_by_device={}
    for message in messages:
        for item in message.get("evidence", []):
            if item.get("observation_only"):
                continue
            evidence_by_pair.setdefault((item.get("device_id"), item.get("metric")), item)
            values_by_device.setdefault(item.get("device_id"), {})[item.get("metric")]=item.get("value")
    for proposal in proposals if isinstance(proposals,list) else []:
        if not isinstance(proposal,dict): continue
        device,metric,cause=proposal.get("device_id"),proposal.get("metric"),proposal.get("cause")
        try: likelihood=float(proposal.get("likelihood"))
        except (TypeError,ValueError): continue
        matched = evidence_by_pair.get((device, metric))
        if matched is None or metric not in allowed.get(cause,set()) or not 0<=likelihood<=.95: continue
        values=values_by_device.get(device,{})
        verified=(cause=="Link congestion" and (values.get("link_utilization_pct",0)>=_threshold("congestion_link_anchor_pct","device",70) or values.get("queue_drops",0)>_threshold("congestion_queue_anchor","device",50))) or (cause=="Weak Wi-Fi" and (values.get("signal_strength_dbm",0)<=_threshold("signal_strength_dbm","device",-75) or values.get("retransmissions_pct",0)>=_threshold("retransmissions_pct","device",15))) or (cause=="Hardware failure" and (values.get("cpu_utilization_pct",0)>=_threshold("cpu_utilization_pct","device",85) or values.get("memory_utilization_pct",0)>=_threshold("memory_utilization_pct","device",90) or str(values.get("device_status","")).lower() in {"critical","failed"})) or (cause=="Ethernet/interface fault" and values.get("interface_errors",0)>_threshold("interface_errors","device",10)) or (cause=="DNS/DHCP service failure" and (values.get("service_status",1)<1 or str(values.get("service_availability","")).lower() in {"warning","critical","down","failed"})) or (cause=="Latency spike" and values.get("latency_ms",0)>=_threshold("latency_ms","device",100) and (values.get("jitter_ms",0)>=_threshold("jitter_ms","device",30) or values.get("packet_loss_pct",0)>=_threshold("packet_loss_pct","device",2)))
        if not verified: continue
        for message in messages:
            for item in message.get("evidence",[]):
                if item is matched:
                    hs=item.setdefault("hypotheses",[])
                    existing=next((h for h in hs if h.get("cause")==cause),None)
                    if existing: existing["likelihood"]=max(existing.get("likelihood",0),likelihood); existing["origin"]="model"
                    else: hs.append({"cause":cause,"likelihood":likelihood,"origin":"model"})

def _rounded(value):
    """Round public numeric output only after all scoring is complete."""
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, list):
        return [_rounded(item) for item in value]
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    return value


def run_diagnosis(payload:Any, model_reviewer=None, model_hypothesizer=None, agent_transport=None,
                  as_of: datetime | None = None, seed: int | str = 0, deterministic_ids: bool = False):
    """Run the agent pipeline. ``as_of`` controls freshness checks."""
    if as_of is not None and isinstance(as_of, str):
        as_of = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    if as_of is None and deterministic_ids:
        raw_records = payload if isinstance(payload, list) else payload.get("records", []) if isinstance(payload, dict) else []
        source_times = []
        for row in raw_records:
            if isinstance(row, dict) and row.get("timestamp"):
                try:
                    parsed = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00"))
                    source_times.append(parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed)
                except (ValueError, TypeError):
                    pass
        as_of = max(source_times) if source_times else datetime(2000, 1, 1, tzinfo=timezone.utc)
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    _ID_CONTEXT.set({"deterministic": deterministic_ids, "seed": str(seed), "counter": 0,
                     "timestamp": as_of if deterministic_ids else None})
    records,warnings,topology=normalize_records(payload, as_of=as_of); messages=[]; failures=[]; conversation_id=_new_id("conversation", {"seed": seed, "records": records})
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
    warnings = _cap_warnings(warnings)
    try:
        corr=correlation_agent(messages, records)
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
        report={"incident_id":"INC-"+_new_id("incident_failure", {"error":type(exc).__name__})[:8].upper(),"status":"insufficient_evidence","suspected_root_cause":"Insufficient evidence to identify a probable root cause","confidence":0.0,"affected_devices":[],"supporting_evidence":[],"alternative_causes":[],"tied_candidates":[],"ranked_candidates":corr["ranked_candidates"],"recommended_actions":["Review the input and collect another time-aligned sample."],"evidence_sources":[],"limitations":list(dict.fromkeys([*warnings,f"Agent reporting_agent failed: {type(exc).__name__}."])),"conflicts":[],"confidence_breakdown":{"base":0,"penalties":{},"agent_failures":.05*len(failures),"final":0}}
    groups = {}
    for row in records:
        groups.setdefault((row["device_id"], row.get("site", "Unknown segment")), []).append(row)
    evidence_index = []
    for message in messages:
        per_device = {}
        for item in message.get("evidence", []):
            per_device.setdefault(item.get("device_id"), []).append(item)
        evidence_index.append(per_device)
    incident_reports = []
    for (device_id, segment), group_records in groups.items():
        group_correlation = corr.get("device_results", {}).get(device_id, {
            "ranked_candidates": [], "winner": None, "ambiguous": False
        })
        unreachable = any(row["status"].lower() == "down" and not row["metrics"] for row in group_records)
        if not group_correlation["winner"] and not group_correlation["ambiguous"] and not unreachable:
            continue
        scoped_messages = []
        for message_index, message in enumerate(messages):
            scoped = dict(message)
            scoped["evidence"] = evidence_index[message_index].get(device_id, [])
            scoped_messages.append(scoped)
        group_correlation = dict(group_correlation, message=corr["message"])
        try:
            group_report = reporting_agent(group_correlation, group_records, warnings, scoped_messages, failures, topology)
        except Exception:
            continue
        if group_report["status"] in {"diagnosed", "low_confidence", "ambiguous"}:
            incident_reports.append({"incident_id": group_report["incident_id"], "device_ids": [device_id],
                                     "segment": segment, "cause": group_report["suspected_root_cause"],
                                     "confidence": group_report["confidence"], "status": group_report["status"],
                                     "evidence": group_report["supporting_evidence"],
                                     "recommended_actions": group_report["recommended_actions"]})
    if incident_reports:
        incident_reports.sort(key=lambda item: (cause_priority(item["cause"]), item["confidence"]), reverse=True)
        selected_device = incident_reports[0]["device_ids"][0]
        selected_records = groups[(selected_device, incident_reports[0]["segment"])]
        selected_messages = []
        for message_index, message in enumerate(messages):
            scoped = dict(message)
            scoped["evidence"] = evidence_index[message_index].get(selected_device, [])
            selected_messages.append(scoped)
        selected_correlation = dict(corr.get("device_results", {}).get(selected_device, {
            "ranked_candidates": [], "winner": None, "ambiguous": False
        }), message=corr["message"])
        report = reporting_agent(selected_correlation, selected_records, warnings, selected_messages, failures, topology)
    report["incidents"] = incident_reports
    corr_message=corr["message"]; corr_message["target_agent"]="reporting_agent"; corr_message["conversation_id"]=conversation_id
    corr_message["in_reply_to"]=messages[0]["message_id"] if messages else None
    messages.append(corr_message)
    if model_reviewer is not None:
        try:
            model_review=model_reviewer(report,messages)
            review_errors=list(MODEL_REVIEW_VALIDATOR.iter_errors(model_review))
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
    report_error=_validate_report(report)
    if report_error: raise ValueError(f"Invalid diagnostic report: {report_error}")
    warnings = _cap_warnings(warnings)
    output = _rounded({"records":records,"topology":topology,"warnings":warnings,"agent_messages":messages,"ranked_candidates":corr["ranked_candidates"],"report":report})
    output["messages_json"] = json.dumps(output["agent_messages"],indent=2,allow_nan=False)
    output["ranked_candidates"] = output["report"].get("ranked_candidates", output["ranked_candidates"])
    return output
