# Stochastix AI

> **Explainable cross-merchant risk intelligence for coordinated payment abuse.**

A payment can look normal in isolation. **Stochastix AI asks whether it is part of a coordinated attack across merchants.**

Stochastix AI is an AI-powered payment risk detection prototype that identifies coordinated card-testing and payment abuse patterns by combining real-time behavioural evidence, machine learning, deterministic policy decisions, audit logging, and explainable incident analysis.

---

## The Problem

A payment platform serving multiple merchants can observe patterns that a single merchant cannot.

For example, an attacker testing stolen cards may attempt small transactions across multiple merchants:

```text
Merchant A → Payment attempt
Merchant B → Payment attempt
Merchant C → Payment attempt
Merchant D → Payment attempt
Each transaction may look harmless individually. But when the same device, IP, card behaviour, timing, or merchant hopping pattern is observed across merchants, it may indicate coordinated abuse.
Stochastix AI helps answer:
Is this transaction normal in isolation, or part of a larger coordinated attack?

How It Works
Payment Event
      ↓
Cross-Merchant Evidence Collection
      ↓
Redis Sliding Windows
      ↓
Behavioural Features
      ↓
LightGBM Risk Model
      ↓
Risk Score
      ↓
Deterministic Policy Engine
      ↓
ALLOW / 3DS STEP-UP / BLOCK
      ↓
Audit Trail + Incident Guardrail
      ↓
Explainable Dashboard
The project separates risk estimation from the final payment decision.
Machine learning estimates risk, while deterministic policy logic selects the final action.
Key Features
- Cross-merchant risk detection using device, IP, card activity, timing, and merchant diversity.
- Redis sliding windows for fast real-time behavioural evidence.
- TTL-based Redis expiry to prevent temporary evidence from accumulating indefinitely.
- LightGBM risk model with asymmetric prototype business costs.
- Deterministic policy layer for ALLOW, 3DS STEP-UP, or BLOCK.
- Explainable dashboard showing evidence → risk → policy decision.
- Durable audit trail for reviewing decisions and observed evidence.
- Agentic incident guardrail for incident analysis and notes.
- FastAPI backend with interactive API documentation.
- Streamlit dashboard for live scenario demonstrations.
Technology Stack
Component	Technology
Backend API	FastAPI
ML Model	LightGBM
Real-Time Evidence	Redis
Dashboard	Streamlit
Visualization	Plotly
Audit Storage	SQLite
Data Processing	Pandas, NumPy
API Server	Uvicorn
Incident Notes	Anthropic API (Optional)


Demo Scenarios
1. Normal Traffic
Independent customers should remain low risk and frictionless.
Low Risk → ALLOW
2. Attack V1 — Same Device and IP
Simulates coordinated activity across merchants using the same device and IP.
3. Attack V2 — Rotating IP
The attacker changes IP addresses, while device behaviour and merchant diversity can still provide cross-merchant evidence.
4. Attack V3 — Rotating Device and IP
Simulates a more advanced attacker and demonstrates the honest detection boundary where stronger signals would be needed.
Run the Project
Terminal 1 — Start Redis
Open PowerShell:
wsl
Then inside WSL:
redis-server --daemonize yes
redis-cli ping
Expected output:
PONG
Terminal 2 — Start the FastAPI Backend
cd C:\Dev\Stochastix_AI
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload
API:
http://127.0.0.1:8000
Interactive API documentation:
http://127.0.0.1:8000/docs
Terminal 3 — Start the Streamlit Dashboard
cd C:\Dev\Stochastix_AI
.\.venv\Scripts\Activate.ps1
python -m streamlit run dashboard.py
Open the URL shown in the terminal, typically:
http://localhost:8501
Install Dependencies
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Validate the Pipeline
python test_pipeline.py
This runs the end-to-end validation and prints locally measured evaluation metrics and latency.
Agentic Guardrail
Set ANTHROPIC_API_KEY to enable LLM-generated incident notes.
Without an API key, the project still runs using a safe templated fallback.
The LLM never directly decides whether a payment is allowed, challenged, or blocked.

The safety-critical payment decision path remains deterministic and does not depend on an LLM call succeeding.
Prototype Boundaries
- Data and labels are synthetic.
- No real payment or fraud data is used.
- Latency and model metrics are measured locally.
- Cost figures are illustrative prototype assumptions.
- This is not presented as a production fraud detection system.
- The agentic layer explains incidents but does not make payment decisions.
Project Structure
Stochastix_AI/
├── app/                 # Backend, risk engine, model and policy
├── docs/                # Architecture and evaluation documentation
├── experiments/         # Attack and baseline experiments
├── ml/                  # Model evaluation
├── tests/               # Unit tests
├── dashboard.py         # Streamlit dashboard
├── test_pipeline.py     # End-to-end validation
├── requirements.txt
├── PROJECT_HANDOFF.md
└── README.md
Design Principle
Machine learning improves risk intelligence, while high-impact payment decisions remain controlled, explainable, and auditable.

Evidence
   ↓
Machine Learning Risk Estimation
   ↓
Deterministic Policy Decision
   ↓
Audit + Explanation
Development Handoff
For detailed architecture, API contracts, implementation notes, safe claims, and development context, see:
[`PROJECT_HANDOFF.md`](PROJECT_HANDOFF.md)
Author
Amit Prajapat
B.Tech Computer Science & Engineering
AI/ML and Data Science
Stochastix AI — Detecting coordinated payment abuse by connecting the signals that individual merchants cannot see.
```
