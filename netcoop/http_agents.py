"""Small JSON HTTP service exposing each specialist for cross-process calls."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from .agents import normalize_records, performance_agent, infrastructure_agent, connectivity_agent, correlation_agent, reporting_agent, _envelope

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            payload=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))))
            if self.path=="/agents/correlation":
                result=correlation_agent(payload.get("messages",[]))
                body=json.dumps(result,allow_nan=False).encode()
                self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
            if self.path=="/agents/reporting":
                corr=payload.get("correlation",{}); records=payload.get("records",[]); warnings=payload.get("warnings",[]); messages=payload.get("messages",[]); topology=payload.get("topology",{})
                report=reporting_agent(corr,records,warnings,messages,topology=topology)
                message=_envelope("reporting_agent",[f"Report verdict: {report['suspected_root_cause']} ({report['status']})."],report["supporting_evidence"],report["limitations"],target="orchestrator",received=[m["message_id"] for m in messages if isinstance(m,dict) and m.get("message_id")])
                body=json.dumps({"report":report,"message":message},allow_nan=False).encode()
                self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
            records,warnings,topology=normalize_records(payload)
            agents={"/agents/performance":lambda:performance_agent(records),"/agents/infrastructure":lambda:infrastructure_agent(records),"/agents/connectivity":lambda:connectivity_agent(records,topology)}
            if self.path not in agents: self.send_error(404); return
            body=json.dumps({"message":agents[self.path](),"warnings":warnings},allow_nan=False).encode()
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
        except Exception as e:
            body=json.dumps({"error":str(e)}).encode(); self.send_response(400); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)

if __name__=="__main__": HTTPServer(("127.0.0.1",8765),Handler).serve_forever()
