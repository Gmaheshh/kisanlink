# KisanLink — Farm-to-Consumer Platform

**SIH 2026 Prototype · Problem Statement 26033**
*"Multiple intermediaries reduce farmers' earnings and increase consumer prices"*
Ministry of Consumer Affairs, Food & Public Distribution

KisanLink is a working prototype that connects Maharashtra's farmers/FPOs directly
with consumers and bulk buyers — cutting out mandi middlemen — backed by:

- **Real market data**: 16 years (2010–2025) of daily Maharashtra mandi prices for
  20 commodities (100,907 records), sourced from Agmarknet via CEDA (Ashoka University).
- **AI price forecasting**: ARIMA/SARIMA models (auto-selected per commodity by
  holdout accuracy) give farmers a 6-month price outlook, so they know whether to
  sell now or wait.
- **A farmer-vs-consumer savings calculator**, benchmarked against RBI's 2024
  research on farmer share of the consumer rupee.
- **Smart logistics**: every listing is matched to its nearest of 7 collection hubs
  across Maharashtra, with distance and estimated transit time (Haversine formula).
- **A real marketplace**: farmers list produce, buyers (bulk or individual) browse
  and order directly — no mandi commission.

## What's inside

```
kisanlink/
├── backend/
│   ├── main.py              FastAPI app — all API routes + serves the frontend
│   ├── models.py            SQLAlchemy models (Listing, Order)
│   ├── database.py          SQLite setup
│   ├── geo_data.py          District coordinates, collection hubs, distance calc
│   ├── seed.py              Seeds 8 demo listings + 1 demo order
│   ├── commodities_data.json  Forecast + price data for 20 commodities
│   ├── assistant.py         Optional AI chatbot + voice layer (see below)
│   └── kisanlink.db         SQLite database (pre-seeded, ready to run)
└── frontend/
    ├── index.html           Landing page — the problem, the pitch, live forecast
    ├── farmer.html          Farmer dashboard — list produce, see forecast & hub
    ├── buyer.html           Buyer marketplace — browse, filter, order
    └── static/
        ├── style.css, app.js
        ├── chatbot.js        Optional floating chat/voice widget (see below)
        └── vendor/          Tailwind CSS + Chart.js (bundled locally — works
                              fully offline, no internet needed at demo time)
```

## How to run it

You need Python 3.9+.

```bash
cd kisanlink/backend
pip install fastapi uvicorn sqlalchemy pydantic httpx
uvicorn main:app --host 0.0.0.0 --port 8000
```

Then open **http://localhost:8000** in a browser. That's it — the database is
already seeded with 8 demo listings and 1 demo order, and all CSS/JS assets are
bundled locally, so it works even without internet access (handy for a live
demo on unreliable venue wifi).

- `/` — landing page with the problem statement and a live 6-month forecast
- `/farmer` — list produce, see AI price forecast, nearest collection hub
- `/buyer` — browse listings, see savings vs. traditional supply chain, place orders

To reset to a fresh demo state at any point:
```bash
cd backend
rm kisanlink.db
python3 seed.py
```

## How the numbers were built

1. **Data collection**: 100,907 daily mandi price records (2010–2025, 20
   commodities, all Maharashtra) pulled from CEDA's Agmarknet mirror, cleaned
   and outlier-flagged (0.41% flagged via median-ratio method).
2. **Forecasting**: For each commodity, both ARIMA and seasonal SARIMA models
   were grid-searched (by AIC) and evaluated on a genuine 6-month holdout
   (not just in-sample fit). Whichever model generalized better (lower holdout
   MAPE) was kept — stored in `commodities_data.json` as `chosen_model` and
   `holdout_mape_pct`.
3. **Price-gap savings**: Live retail price data (the ideal comparison) was
   unavailable at build time (source outage), so the savings calculator uses
   RBI's October 2024 Terms of Trade study and its 2024 Rabi crop survey —
   real, cited, commodity- and category-level farmer-share-of-consumer-price
   percentages — rather than invented numbers.

## Optional: AI chatbot + voice assistant

The app includes an optional AI assistant (a Claude-powered chat, plus
Sarvam AI speech-to-text/text-to-speech for voice in Indian languages) —
useful for farmers who'd rather ask a question aloud than fill in a form.

**It is off by default and fully additive.** With no keys set, `/api/chat`
and the voice endpoints return a clean "not configured" message, the
floating chat button never even appears on the page, and every other part
of the app (listings, orders, forecasts, hubs) works exactly as before —
nothing about the core app changes whether or not this is turned on.

To turn it on, set one or both environment variables before starting
uvicorn:

```bash
# Windows PowerShell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:SARVAM_API_KEY   = "sk_..."

# macOS/Linux
export ANTHROPIC_API_KEY="sk-ant-..."
export SARVAM_API_KEY="sk_..."

uvicorn main:app --host 0.0.0.0 --port 8000
```

- Set **`ANTHROPIC_API_KEY`** alone → a floating chat button appears with
  text Q&A grounded in the app's live listings and commodity data (get a
  key at [console.anthropic.com](https://console.anthropic.com)).
- Also set **`SARVAM_API_KEY`** → a mic button appears too, for
  speak-a-question / hear-the-answer in Hindi, Marathi, and other Indian
  languages (get a key at [dashboard.sarvam.ai](https://dashboard.sarvam.ai)).
- Neither key costs anything to leave unset — the rest of the demo doesn't
  need them.

## Honest limitations (worth stating to judges)

- Mango's ARIMA/SARIMA forecast has a high error rate (flagged, not hidden) —
  its price series is unusually volatile/seasonal in ways a simple time-series
  model doesn't capture well. A production version would add exogenous
  regressors (arrival volumes, weather).
- The savings calculator uses published research benchmarks, not live retail
  prices, because the live retail data source was down during development.
  This is clearly labeled in the underlying Excel workbook and can be swapped
  for a live feed later.
- This is a functional prototype (SQLite, single server) — a production
  deployment would need auth, payments, a real logistics partner integration,
  and a managed database.

## Supporting deliverables (from the data/modeling phase)

These Excel workbooks were built earlier in this project and back the numbers
used in the app:
- `Maharashtra_Mandi_Prices_2010_2025.xlsx` — the full cleaned dataset
- `Maharashtra_ARIMA_Forecast.xlsx` / `Maharashtra_SARIMA_Forecast.xlsx` —
  model outputs and comparison
- `Farmer_Consumer_Price_Gap.xlsx` — the RBI-benchmarked savings analysis

(Not included in this zip — ask if you'd like them re-sent.)
