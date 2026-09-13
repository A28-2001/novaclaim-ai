# NovaClaim AI — Prior Authorization Document Parser

**Live demo → [novaclaim-ai-geapnrrp2vuegxj4jm5wre.streamlit.app](https://novaclaim-ai-geapnrrp2vuegxj4jm5wre.streamlit.app/)**

---

## 🧠 Data Science & Analytics Skills

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)
![Pandas](https://img.shields.io/badge/Pandas-Data%20Wrangling-150458?logo=pandas&logoColor=white)
![Scikit-learn](https://img.shields.io/badge/Scikit--learn-ML%20Pipeline-F7931E?logo=scikit-learn&logoColor=white)
![Jupyter](https://img.shields.io/badge/Jupyter-EDA%20Notebook-F37626?logo=jupyter&logoColor=white)
![SQL](https://img.shields.io/badge/SQL-SQLite-003B57?logo=sqlite&logoColor=white)
![Matplotlib](https://img.shields.io/badge/Matplotlib-Seaborn-11557c)
![SciPy](https://img.shields.io/badge/SciPy-Statistical%20Testing-8CAAE6?logo=scipy&logoColor=white)

| Skill | What I built |
|---|---|
| **Pandas** | Data wrangling — groupby, merge, pivot, time-series resampling on parsed document records |
| **Scikit-learn** | End-to-end ML pipeline — Logistic Regression + Random Forest ensemble, `Pipeline`, `cross_val_score`, `roc_auc_score`, feature importance |
| **Statistical Analysis** | Mann-Whitney U test (SciPy) to validate completeness vs. denial correlation; custom scoring models for risk and denial probability |
| **Data Visualization** | Matplotlib, Seaborn — ROC curves, confusion matrices, correlation heatmaps, approval rate trends, payor benchmarking charts |
| **Exploratory Data Analysis** | `analysis.ipynb` — 25-cell Jupyter notebook covering distributions, missing value analysis, temporal trends, and feature engineering |
| **SQL** | Aggregation queries, `json_each()` for nested arrays, trend queries, audit logging — all computed SQL-side |
| **Feature Engineering** | 10 numerical features derived from raw document fields (binary presence flags, historical payor rates, completeness scores) |
| **Model Evaluation** | Holdout split, stratified k-fold CV, classification report, ROC-AUC, confusion matrix |
| **Data Export** | CSV and Excel (openpyxl) export from the analytics dashboard |
| **REST API Integration** | CMS NPI registry, NIH ICD-10 API, FDA drug database, Groq LLM API |

---

## What the Project Does

NovaClaim AI is an end-to-end prior authorization intelligence platform built for healthcare workflows. Upload a prior auth document (PDF or TXT) and get a structured, AI-powered breakdown in seconds — no manual chart review required.

Prior authorization documents are dense, inconsistently formatted, and time-consuming to review. NovaClaim AI parses them automatically and surfaces the information that matters:

- **Completeness scoring** — measures how much required information is present across clinical and administrative fields
- **Field extraction** — pulls patient info, diagnosis codes, procedure codes, prescribing physician, NPI, drug details, dates, and insurance data
- **ML-powered denial predictor** (`denial_predictor.py`) — Logistic Regression + Random Forest ensemble trained on historical records; falls back to rule-based scoring when data is insufficient
- **EDA notebook** (`analysis.ipynb`) — approval rate analysis, payor benchmarking, feature importance, ROC curves, and key operational insights
- **Risk assessment** — scores the likelihood of denial based on document completeness and field patterns
- **Manual vs. AI comparison** — side-by-side view showing time and cost savings over traditional review
- **Persistent history** — all parsed documents are logged in a local SQLite database with full audit trail
- **Analytics dashboard** — approval rates, average completeness, processing history, and trends over time

---

## Full Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Frontend / UI | Streamlit |
| AI / LLM | Groq API (`openai/gpt-oss-20b`, configurable via `GROQ_MODEL`) |
| NLP / text extraction | PyMuPDF, regex, structured prompt engineering |
| Data manipulation | Pandas |
| Data visualization | Matplotlib, Seaborn, Plotly, Streamlit native charts |
| Machine learning | Scikit-learn — Logistic Regression, Random Forest, Pipeline, cross_val_score, ROC-AUC |
| Statistical analysis | SciPy (Mann-Whitney U), custom scoring models |
| Database | SQLite — SQL aggregations, json_each(), trend queries, audit logging |
| Data export | CSV, Excel (openpyxl) |
| Exploratory analysis | Jupyter notebook (`analysis.ipynb`) |
| REST API integration | Groq, CMS NPI registry, NIH ICD-10 API, FDA drug API, SMTP/Gmail |
| Deployment | Streamlit Cloud |
| Version control | Git, GitHub (SSH) |
| Secrets management | Streamlit Cloud secrets (`.toml`, gitignored) |

---

## Run Locally

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

## Environment Variables

| Variable | Description |
|---|---|
| `GROQ_API_KEY` | Groq API key for LLM inference |
| `GROQ_MODEL` | *(optional)* Override the Groq model ID. Defaults to `openai/gpt-oss-20b`. Set this if Groq deprecates the default — see [current models](https://console.groq.com/docs/models). |
| `SMTP_EMAIL` | Gmail address for email alerts |
| `SMTP_APP_PASSWORD` | Gmail App Password (not your account password) |

Never commit `.streamlit/secrets.toml` — it is excluded via `.gitignore`.

---

## Project Structure

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

Built as a full-stack AI + data science project to demonstrate applied ML in a regulated, document-heavy domain. Prior authorization is one of the most time-consuming administrative tasks in US healthcare — this project explores how AI and predictive modelling can reduce that burden while maintaining structure and auditability.
