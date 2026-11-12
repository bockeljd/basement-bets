import os
import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from src.utils.gemini_rest import generate_content, embed_content
from src.agents.base import BaseAgent
from src.agents.contracts import EventContext, DecisionRun, AgentTrace
from src.agents.journal_agent import JournalAgent
from src.database import get_db_connection, _exec

class PostMortemAgent(BaseAgent):
    """
    Runs after games complete. Analyzes the Oracle's prediction vs reality
    and saves a 'lesson learned' back into the vector memory table.
    """
    def __init__(self):
        super().__init__()
        self.journal_agent = JournalAgent()

    def execute(self, context: Dict[str, Any], *args, **kwargs) -> Dict[str, Any]:
        results_list = context.get('completed_games', []) # List of dicts with outcome details
        if not results_list:
            return {"status": "No games to analyze"}

        memories_added = 0
        from src.agents.research_agent import ResearchAgent
        research_agent = ResearchAgent()

        with get_db_connection() as conn:
            unreviewed = {}
            unreviewed_raw = {}
            for game in results_list:
                team_a = game.get('away_team')
                team_b = game.get('home_team')
                prediction = game.get('oracle_prediction', 'Unknown')
                actual_result = game.get('actual_result', 'Unknown')
                rec_bet = game.get('recommended_bet', 'N/A')
                game_date = game.get('game_date') or datetime.now().strftime("%Y-%m-%d")
                
                # Check if we already reviewed this specific game on this date
                exists_query = """
                    SELECT id FROM agent_memories 
                    WHERE team_a = %s AND team_b = %s 
                    AND (lesson LIKE %s OR DATE(timestamp) = CURRENT_DATE)
                """
                date_pattern = f"%%({game_date})%%"
                row = _exec(conn, exists_query, (team_a, team_b, date_pattern)).fetchone()
                if row:
                    continue
                
                # Fetch game facts/recap
                recap_data = "No recap found."
                try:
                    ev_ctx = EventContext(event_id="temp", league="NCAAM", home_team=team_b, away_team=team_a, start_time=game_date)
                    research_ctx = {"events": [ev_ctx]}
                    # Custom research query for recap
                    research_res, _ = research_agent.run(research_ctx)
                    # Research agent returns dict by event_id, wait, research_agent uses ev.event_id as key
                    res = research_res.get("temp", {})
                    citations = res.get("citations", [])
                    if citations:
                        recap_data = "\n".join([f"- {c['title']}: {c['snippet']}" for c in citations])
                except Exception as e:
                    print(f"[PM Agent] Recap search failed: {e}")

                key = f"{team_a} vs {team_b} ({game_date})"
                unreviewed[key] = {
                    "matchup": f"{team_a} vs {team_b}",
                    "date": game_date,
                    "prediction_context": prediction,
                    "actual_outcome": actual_result,
                    "recommended_bet": rec_bet,
                    "game_recap_snippets": recap_data
                }
                unreviewed_raw[key] = {**game, "derived_date": game_date}

            if not unreviewed:
                return {"status": "success", "memories_generated": 0}

            full_prompt = f"""
You are the Post-Mortem Auditor for a high-performance sports betting syndicate.
Your goal is to extract deep, factual lessons from completed college basketball matchups to improve future model predictions.

Data (keyed by matchup with date):
{json.dumps(unreviewed, ensure_ascii=False, indent=2)}

Task:
For EACH matchup, perform a rigorous analysis:
1. Compare the `recommended_bet` and `prediction_context` against the `actual_outcome`.
2. Analyze the `game_recap_snippets` for specific factual details: 
   - Point distributions (e.g., "Team X dominated the paint 40-20").
   - Shooting efficiency (e.g., "Team Y shot 15% from 3PT range").
   - Turnover/Rebound margins.
   - Specific scoring droughts or momentum shifts.
3. Formulate a 'lesson' that identifies WHY the model was right or wrong. 

Return VALID JSON where keys are the exact matchup strings, and values are objects with these keys:
{{
  "matchup_key": {{
      "result": "WON|LOST|PUSH|VOID",
      "lesson": "2-4 sentences. Include at least TWO specific game facts (stats, droughts, margins). Do not hallucinate stats if not in the recap.",
      "primary_driver": "What was the main reason for the outcome? (e.g. Offensive rebounding, Cold shooting, Tempo control)",
      "missed_signal": "What should the model/agents have seen beforehand?",
      "followup_check": "What specific team metric should we track more closely for these teams?",
      "tags": ["injury","rotation","pace","efficiency","rebounding","turnovers","clutch_fail","variance"]
  }}
}}

Rules:
- DO NOT invent stats. If recaps are vague, focus on the result but demand factual grounding.
- The 'lesson' must be formatted as a single cohesive paragraph.
"""

            try:
                response_text = generate_content(
                    model="gemini-2.5-flash-lite" if os.environ.get("VERCEL") else "gemini-2.0-flash",
                    system_prompt=full_prompt,
                    json_mode=True,
                    max_tokens=4000,
                    timeout=15 if os.environ.get("VERCEL") else 25,
                    retries=2,
                )
                if not response_text:
                    parsed_lessons = {}
                else:
                    clean_text = response_text.strip()
                    if clean_text.startswith("```json"):
                        clean_text = clean_text[7:]
                    if clean_text.endswith("```"):
                        clean_text = clean_text[:-3]

                    self.log_trace("Post-mortem response received", {"raw_json": clean_text.strip()})
                    parsed_lessons = json.loads(clean_text.strip())

                for key, lesson_obj in parsed_lessons.items():
                    if key not in unreviewed_raw:
                        continue
                    
                    raw_game = unreviewed_raw[key]
                    team_a = raw_game.get('away_team')
                    team_b = raw_game.get('home_team')
                    rec_bet = raw_game.get('recommended_bet', 'N/A')
                    game_date = raw_game.get('derived_date', 'Unknown Date')
                    
                    lesson_text = ""
                    status = "UNKNOWN"
                    if isinstance(lesson_obj, dict):
                        lesson_text = lesson_obj.get('lesson', str(lesson_obj))
                        status = str(lesson_obj.get('result', 'UNKNOWN')).upper()
                    else:
                        lesson_text = str(lesson_obj)
                        
                    # Format: [STATUS] (DATE) BET: LESSON
                    display_lesson = f"[{status}] ({game_date}) {rec_bet}: {lesson_text}"
                        
                    full_context_json = json.dumps(lesson_obj, ensure_ascii=False)
                    
                    try:
                        # 2. Get Embedding
                        embed_res = embed_content(
                            model="models/gemini-embedding-001",
                            title="Reflection",
                            task_type="RETRIEVAL_DOCUMENT",
                            content=lesson_text
                        )
                        
                        self.log_trace(f"Generated embedding for {team_a} vs {team_b}", {"embedding_size": len(embed_res)})
                        
                        # 3. Save to memory DB
                        insert_query = """
                            INSERT INTO agent_memories (team_a, team_b, context, lesson, timestamp, embedding_json)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """
                        _exec(conn, insert_query, (
                            team_a, team_b, full_context_json, display_lesson, 
                            datetime.now(timezone.utc), json.dumps(embed_res)
                        ))
                        conn.commit()
                        memories_added += 1
                    except Exception as ei:
                        print(f"[PM Agent] Failed to embed/save reflection for {team_a} vs {team_b}: {ei}")
                        self.log_trace(f"Memory save failed for {team_a} vs {team_b}", {"error": str(ei)})
                        conn.rollback()

            except Exception as e:
                print(f"[PostMortemAgent] Failed to process batch: {e}")
                self.log_trace("Batch processing failed", {"error": str(e)})

        # Persist traces even if no memories were added
        try:
            run_id = f"PM-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            decision_run = DecisionRun(
                run_id=run_id,
                created_at=datetime.now(timezone.utc).isoformat(),
                league="NCAAM", 
                status="OK",
                inputs_hash="post_mortem_run",
                offers_count=0,
                recommendations=[],
                rejected_offers=[],
                notes=["Post-mortem agent summary run"],
                errors=[],
                model_version=self.version,
                agent_traces=self._traces
            )
            self.journal_agent.run({"action": "persist", "decision_run": decision_run})
        except Exception as e:
            print(f"[PostMortemAgent] Failed to persist traces: {e}")

        return {"status": "success", "memories_generated": memories_added}
