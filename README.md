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
- **ML denial modelling** (`analysis.ipynb`, `denial_predictor.py`) — Logistic Regression + Random Forest ensemble trained and evaluated in the notebook, packaged in `denial_predictor.py`; not yet wired into the live app (see [Limitations](#limitations-and-next-steps))
- **EDA notebook** (`analysis.ipynb`) — approval rate analysis, payor benchmarking, feature importance, ROC curves, and key operational insights
- **Risk assessment** (`risk_scorer.py`) — rule-based 0–100 approval-likelihood score from five weighted signals: completeness, validation, agent verification, coverage, and payer history
- **Manual vs. AI comparison** — side-by-side view showing time and cost savings over traditional review
- **Persistent history** — all parsed documents are logged in a local SQLite database with full audit trail
- **Analytics dashboard** — approval rates, average completeness, processing history, and trends over time

---

## Evaluation

<!-- EVAL:START -->
_Last run 2026-10-05 · model `openai/gpt-oss-20b` · reproduce with `python evaluate.py`_

Extraction was scored against hand labels on **12 synthetic prior authorization documents** (8 full-length forms, 1 of them a PDF, and 4 short forms) across **14 fields**, 168 field instances in total. Labels and labeling rules are in [`eval/ground_truth.json`](eval/ground_truth.json).

| Metric | Result |
|---|---|
| Field-level accuracy | **100.0%** (168 / 168) |
| Recall on fields present in the document | 100.0% |
| Hallucination rate on fields absent from the document | 0.0% (0 / 9) |
| Documents parsed successfully | 12 / 12 |
| Documents with every field correct | 12 / 12 |
| Median extraction time (one LLM call) | 1.0 s (max 11.1 s) |
| Median end-to-end time (extraction + 4 agents) | 1.8 s (max 11.9 s) |
| Field accuracy, full-form documents | 100.0% |
| Field accuracy, short-form documents | 100.0% |

<details><summary>Per-field accuracy</summary>

| Field | Correct | Accuracy |
|---|---|---|
| Patient name | 12 / 12 | 100% |
| Date of birth | 12 / 12 | 100% |
| Member ID | 12 / 12 | 100% |
| Provider name | 12 / 12 | 100% |
| Provider NPI | 12 / 12 | 100% |
| Facility | 12 / 12 | 100% |
| ICD-10 code(s) | 12 / 12 | 100% |
| Treatment requested | 12 / 12 | 100% |
| CPT code(s) | 12 / 12 | 100% |
| Payer | 12 / 12 | 100% |
| Plan name | 12 / 12 | 100% |
| Decision status | 12 / 12 | 100% |
| Decision date | 12 / 12 | 100% |
| Authorization number | 12 / 12 | 100% |

</details>

Every labeled field was extracted correctly on this run.

**How it's scored.** A field counts as correct when it matches the label under a rule for its type: names ignore honorifics and middle initials, organizations ignore spacing and punctuation, IDs and NPIs must match exactly, dates are compared after normalizing the format, and ICD-10/CPT codes must match as an exact set. Where a field is absent from the document, the only correct answer is to return nothing. Filling it in counts as a hallucination. Full rules are in the docstring of [`evaluate.py`](evaluate.py).

**Read these numbers as an upper bound.** The documents are synthetic, cleanly formatted, and the same ones the extraction prompt was developed against. Real payer forms (scanned faxes, inconsistent layouts, handwriting) will score lower. LLM output also varies slightly between runs.
<!-- EVAL:END -->

---

## Limitations and next steps

NovaClaim AI is a portfolio prototype. It has only been run on synthetic documents and must not be used with real patient data.

- **Synthetic documents only.** Every test document and in-app sample is synthetic, cleanly formatted, and was available while the extraction prompt was written. The accuracy above is an optimistic upper bound, not an estimate of performance on real payer forms.
- **No OCR.** PDFs are read through PyPDF2's text layer. Scanned or faxed forms, which are common in prior authorization, return no text and fail to parse.
- **The denial-risk score in the app is rule-based.** `risk_scorer.py` combines five weighted signals into a 0–100 score. The Logistic Regression and Random Forest models are trained and evaluated in `analysis.ipynb` on synthetic data. `denial_predictor.py` packages that ensemble but isn't wired into the app yet, because predicting denials meaningfully needs real, labeled payer outcomes.
- **Coverage check uses a reference list, not payer policy.** The CPT agent checks codes against an embedded list of procedures that commonly require prior authorization, plus NLM's public procedure lookup. It does not query any specific payer's current rules.
- **Confidence badges are self-reported.** The high/medium/low confidence on each field is the LLM's own judgment, not a calibrated probability.
- **Not HIPAA-ready.** Document text is sent to a third-party LLM API (Groq) with no business associate agreement, and records are stored unencrypted in SQLite. On Streamlit Community Cloud that storage also resets whenever the container restarts.

**Next steps**

1. **Portal submission.** Turn a validated extraction into a submitted request rather than a report. The target is the FHIR-based Prior Authorization API that CMS-0057-F requires Medicare Advantage, Medicaid, CHIP and federal Marketplace plans to support from January 2027 (HL7 Da Vinci PAS), with X12 278 for payers not yet on FHIR.
2. **A harder evaluation set:** de-identified real forms, scanned and faxed variants, and per-field precision and recall tracked across prompt and model changes.
3. **OCR** for image-only PDFs.
4. **Wire in the ML denial model** once real labeled outcomes exist, and compare it against the rule-based scorer on the same holdout set.
5. **Payer-specific coverage rules** in place of the embedded CPT list.
6. **HIPAA-grade deployment:** BAA-covered model hosting, encryption at rest, authentication and audit logging.

---

## Full Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Frontend / UI | Streamlit |
| AI / LLM | Groq API (`openai/gpt-oss-20b`, configurable via `GROQ_MODEL`) |
| NLP / text extraction | PyPDF2, regex, structured prompt engineering |
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
git clone https://github.com/A28-2001/novaclaim-ai.git
cd novaclaim-ai
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

To re-run the accuracy evaluation (12 labeled documents, a few minutes):

```bash
python evaluate.py            # add --no-agents to time extraction only
python evaluate.py --self-test   # checks the scorer itself, no API calls
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
├── demo_data.py             # Seeds fresh deploys with real parsed samples; labeled demo rows
├── evaluate.py              # Field-level extraction accuracy on the labeled test set
├── eval/
│   ├── ground_truth.json    # Hand labels + labeling rules for 12 synthetic documents
│   ├── results.json         # Latest evaluation metrics and every miss
│   └── parsed_outputs.json  # Real parser outputs from the latest evaluation run
├── analysis.ipynb           # EDA notebook — approval analysis, ML evaluation
├── .streamlit/
│   └── secrets.toml         # Local secrets (gitignored)
├── requirements.txt
└── prior_auth.db            # SQLite database (gitignored)
```

---

## Background

Built as a full-stack AI + data science project to demonstrate applied ML in a regulated, document-heavy domain. Prior authorization is one of the most time-consuming administrative tasks in US healthcare — this project explores how AI and predictive modelling can reduce that burden while maintaining structure and auditability.
