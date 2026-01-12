# Basement Bets 🏠💰

**Basement Bets** is a private, self-hosted betting analytics platform. It serves as your historical transaction ledger, tracking performance across multiple sportsbooks (DraftKings & FanDuel).

## 🚀 Features
- **Ledger**: Permanent record of your betting history in `data/imports/`.
- **Dashboard**: "Glassmorphism" UI with Net Profit, ROI, and Win Rate.
- **Provider Support**: Auto-detects text exports from DraftKings and FanDuel.
- **Privacy**: Your database (`bets.db`) is local and git-ignored. Only raw text history is tracked.

## 📂 Workflow: How to Add Bets
1.  **Copy**: Copy the "Transaction History" or "Card View" text from your sportsbook app.
2.  **Save**: Paste it into a new text file in `data/imports/` (e.g., `data/imports/2026-01-20_dk_wins.txt`).
3.  **Commit**: (Optional) `git add . && git commit -m "Added weekend wins"` to save history.
4.  **Ingest**: Run:
    ```bash
    python3 main.py ingest
    ```
5.  **View**: Open the dashboard.
    ```bash
    ./run.sh
    ```

## 🛠️ Setup
1.  **Install**:
    ```bash
    pip install fastapi uvicorn
    cd client && npm install
    ```
2.  **Run**:
    ```bash
    ./run.sh
    ```
    - API: http://localhost:8000
    - UI: http://localhost:5173

## 🏗️ Project Structure
```text
basement-bets/
├── data/
│   ├── imports/       # RAW TEXT FILES (Tracked in Git)
│   └── bets.db        # SQLite Database (Ignored)
├── src/               # Python Backend & Parsers
├── client/            # React Frontend
└── main.py            # CLI Tools
```
