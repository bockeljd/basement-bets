
import os
import json
import openai
from datetime import datetime, timedelta
from src.database import get_db_connection, _exec

class AiAnalysisService:
    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        if self.api_key:
            openai.api_key = self.api_key
        self.model = "gpt-4-turbo-preview"

    def analyze_model_health(self, target_date: str = None) -> dict:
        """
        Fetches daily metrics and asks LLM for insights.
        """
        if not target_date:
            target_date = datetime.now().strftime("%Y-%m-%d")
            
        print(f"[AI Analysis] Running for {target_date}...")
        
        # 1. Fetch recent stats (last 7 days for trend context)
        start_date = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
        
        with get_db_connection() as conn:
            # Fetch aggregated metrics by day and league
            q = """
            SELECT date, league, metric_name, metric_value, sample_size
            FROM model_health_daily
            WHERE date >= :start_date AND date <= :end_date
            ORDER BY date, league
            """
            rows = _exec(conn, q, {"start_date": start_date, "end_date": target_date}).fetchall()
            
        if not rows:
            print("[AI Analysis] No data found for analysis.")
            return {"error": "no_data"}

        # Format data for LLM
        # Group by Date -> League -> Metrics
        data_summary = []
        for r in rows:
            data_summary.append(f"{r['date']} | {r['league']} | {r['metric_name']} = {r['metric_value']} (N={r['sample_size']})")
            
        context_text = "\n".join(data_summary)
        
        prompt = f"""
        You are a quantitative betting analyst. I will provide a log of daily model performance metrics (ROI, CLV, Brier Score, Hit Rate) for the last 7 days.
        
        Your Goal: Identify statistically significant drifts or anomalies.
        
        Metrics:
        - ROI: Profitability (>0 is good).
        - CLV Diff: Closing Line Value (positive implies we beat the market).
        - Brier Score: Calibration (lower is better).
        
        Data Log:
        {context_text}
        
        Instructions:
        1. Analyze the trend. Are we improving or degrading in specific leagues?
        2. Flag any "Leakage" (e.g. high CLV but negative ROI, or extremely poor Brier score).
        3. Generate 1 hypothesis for why performance might be changing.
        
        Return JSON format:
        {{
            "summary": "Brief summary string",
            "anomalies": ["List of anomalies"],
            "hypothesis": "Hypothesis string",
            "action_items": ["Suggested checks"]
        }}
        """
        
        analysis = None
        
        if not self.api_key:
            print("[AI Analysis] No API Key. Using mock.")
            analysis = {
                "summary": "Mock Analysis (No Key)",
                "anomalies": ["Mock Anomaly 1"],
                "hypothesis": "Mock Hypothesis",
                "action_items": ["Check Mock Data"]
            }
        else:
            try:
                response = openai.ChatCompletion.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a helpful quantitative analyst assistant."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2
                )
                content = response.choices[0].message.content
                analysis = json.loads(content)
            except Exception as e:
                print(f"[AI Analysis] API Error: {e}")
                return {"error": str(e)}

        if analysis:
            # Persist to DB
            try:
                from src.database import store_health_insight
                store_health_insight(analysis, target_date)
                print("[AI Analysis] Insight stored in DB.")
            except Exception as dbe:
                 print(f"[AI Analysis] DB Store Error: {dbe}")
            
            print("[AI Analysis] Results:")
            print(json.dumps(analysis, indent=2))
            return analysis

if __name__ == "__main__":
    svc = AiAnalysisService()
    svc.analyze_model_health()
