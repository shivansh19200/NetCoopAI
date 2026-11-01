# Project goals and where to find them

| Goal | Where it is handled |
|---|---|
| Several specialists share work | Performance, infrastructure, and connectivity agents send findings to the correlation and reporting agents. |
| Agents can work across process boundaries | Messages have unique IDs, timestamps, types, reply links, capability lists, and input-conversion records. HTTP routes let each agent receive requests separately. See [`AGENT_PROTOCOL.md`](AGENT_PROTOCOL.md). |
| The diagnosis can be followed | The dashboard has a message replay and a JSON report. |
| Common network problems can be explored | Demo scenarios cover congestion, weak Wi-Fi, interface faults, hardware problems, and DNS/DHCP issues. |
| Reports explain their conclusions | Reports include the likely cause, evidence, confidence score, alternatives, suggested checks, and limitations. |
| Bad or unusual input is handled | The adapter converts known units and aliases, rejects booleans and infinite values, warns about missing metrics, checks stale readings, and flags devices that are down without readings. |
| Results can be checked again | Automated tests and a seeded 1,000-case audit are included. See [`ACCURACY.md`](ACCURACY.md). |
| Diagnosis speed can be measured | A repeatable benchmark measures median and P95 time plus traced Python memory from 1 to 1,000 records. See [`PERFORMANCE.md`](PERFORMANCE.md). |
| The wider network impact is visible | The topology highlights affected devices and downstream scope. Metric trends and confidence deductions are shown in the dashboard. |
| An AI model can help without owning the answer | Groq can suggest causes and write a summary when enabled; deterministic checks keep control of the verdict. |
| The project can be run and reviewed | A command-line interface, GitHub Actions workflow, and recorded demo are included. |
| Optional operator workflow | The dashboard can save a review, pause and resume a run, and record a proposed fix as a simulation. |
| No automatic network changes | The app does not connect to equipment or run repair commands. |

Run the checks with `python -m pytest tests -q`. Run the randomized audit with `python scripts/accuracy_audit.py`.
