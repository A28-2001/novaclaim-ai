# NovaClaim AI — Prior Authorization Document Parser

**Live demo → [novaclaim-ai-geapnrrp2vuegxj4jm5wre.streamlit.app](https://novaclaim-ai-geapnrrp2vuegxj4jm5wre.streamlit.app/)**

NovaClaim AI is an end-to-end prior authorization intelligence platform built for healthcare workflows. Upload a prior auth document (PDF or TXT) and get a structured, AI-powered breakdown in seconds — no manual chart review required.

---

## What it does

Prior authorization documents are dense, inconsistently formatted, and time-consuming to review. NovaClaim AI parses them automatically and surfaces the information that matters:

- **Completeness scoring** — measures how much required information is present across clinical and administrative fields
- **Field extraction** — pulls patient info, diagnosis codes, procedure codes, prescribing physician, NPI, drug details, dates, and insurance data
- **Coverage analysis** — flags which fields are present, missing, or ambiguous
- **Risk assessment** — scores the likelihood of denial based on document completeness and field patterns
- **Manual vs. AI comparison** — side-by-side view showing time and cost savings over traditional review
- **Persistent history** — all parsed documents are logged in a local SQLite database with full audit trail
- **Analytics dashboard** — approval rates, average completeness, processing history, and trends over time

---

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Frontend / UI | Streamlit |
| AI / LLM | Groq API (Llama 3.3 70B) |
| NLP / text extraction | PyMuPDF, regex, structured prompt engineering |
| Data manipulation | Pandas (groupby, merge, pivot, time-series resampling) |
| Data visualization | Matplotlib, Seaborn, Plotly, Streamlit native charts |
| Machine learning | Scikit-learn — Logistic Regression, Random Forest, Pipeline, cross_val_score, ROC-AUC |
| Statistical analysis | SciPy (Mann-Whitney U), custom scoring models (completeness, risk, denial probability) |
| Database | SQLite — SQL aggregations, json_each(), trend queries, audit logging |
| Data export | CSV, Excel (openpyxl) |
| REST API integration | Groq REST API, CMS NPI registry, NIH ICD-10 API, FDA drug API, SMTP/Gmail |
| Exploratory analysis | Jupyter notebook with synthetic + live data fallback (`analysis.ipynb`) |
| Deployment | Streamlit Cloud |
| Version control | Git, GitHub (SSH) |
| Secrets management | Streamlit Cloud secrets (`.toml`, gitignored) |

---

## Features at a glance

- Multi-file upload — parse several documents in one session
- Completeness score (0–100%) with field-by-field breakdown
- Color-coded risk levels (Low / Medium / High / Critical)
- Per-document expandable results with status banners
- Side-by-side Manual vs. AI comparison table
- Analytics sidebar with historical trends
- ML-powered denial predictor (`denial_predictor.py`) — Logistic Regression + Random Forest ensemble, trains on historical records in SQLite, falls back to rule-based scoring when data is insufficient
- Jupyter EDA notebook (`analysis.ipynb`) — approval rate analysis, payor benchmarking, feature importance, ROC curves, and key operational insights

---

## Run locally

```bash
git clone git@github.com:<your-username>/prior-authorization-document-parser.git
cd prior-authorization-document-parser
pip install -r requirements.txt
```

Create `.streamlit/secrets.toml`:

```toml
GROQ_API_KEY = "gsk_..."
SMTP_EMAIL = "you@gmail.com"
SMTP_APP_PASSWORD = "your-app-password"
```

Then run:

```bash
streamlit run Home.py
```

---

## Environment variables

| Variable | Description |
|---|---|
| `GROQ_API_KEY` | Groq API key for LLM inference |
| `SMTP_EMAIL` | Gmail address for email alerts |
| `SMTP_APP_PASSWORD` | Gmail App Password (not your account password) |

Never commit `.streamlit/secrets.toml` — it is excluded via `.gitignore`.

---

## Project structure

```
├── Home.py                  # Main app — upload, parse, results
├── pages/
│   ├── Analytics.py         # Dashboard with historical trends
│   └── History.py           # Full document history log
├── denial_predictor.py      # ML pipeline — LR + RF denial risk model
├── risk_scorer.py           # Rule-based risk scoring (Agent 4)
├── validation_agent.py      # NPI / ICD-10 / drug verification (Agent 1)
├── coverage_agent.py        # CPT coverage checker (Agent 2)
├── appeal_agent.py          # Appeal letter generator (Agent 3)
├── database.py              # SQLite ORM + SQL analytics queries
├── analysis.ipynb           # EDA notebook — approval analysis, ML evaluation
├── .streamlit/
│   └── secrets.toml         # Local secrets (gitignored)
├── requirements.txt
└── prior_auth.db            # SQLite database (gitignored)
```

---

## Background

Built as a full-stack AI project to demonstrate applied LLM usage in a regulated, document-heavy domain. Prior authorization is one of the most time-consuming administrative tasks in US healthcare — this project explores how AI can reduce that burden while maintaining structure and auditability.
