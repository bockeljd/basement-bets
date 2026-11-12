import os
import json
from typing import Any, Dict, List
from src.utils.gemini_rest import generate_content
from src.agents.base import BaseAgent
from src.agents.contracts import EventContext, MarketOffer, FairPrice

class OracleAgent(BaseAgent):
    """
    Synthesizes numerical edges, web research, and retrieved RAG memories 
    into a structured debate and final prediction decision.

    In addition to returning the council narrative, it persists each event's
    `signals` to the `council_signals` table so downstream consumers and
    offline evaluation can audit every qualitative claim.
    """
    def __init__(self):
        super().__init__()

    def execute(self, context: Dict[str, Any], *args, **kwargs) -> Dict[str, Any]:
        events: List[EventContext] = context.get('events', [])
        quantitative_edges = context.get('edges', {})      # By event_id
        research_data = context.get('research', {})         # By event_id
        memory_data = context.get('memories', {})           # By event_id
        # run_id passed in so we can key council_signals rows
        run_id = context.get('run_id', None)
        
        results = {}
        if not events:
            return results

        matchups_data = []
        for ev in events:
            ev_id = ev.event_id
            quant = quantitative_edges.get(ev_id, "No quantitative edge data available.")
            
            # Build evidence: include extracted facts from ResearchAgent if available
            research = research_data.get(ev_id, {})
            citations = research.get("citations", [])
            facts = research.get("facts", [])
            evidence_str = json.dumps({
                "raw_snippets": citations,
                "extracted_facts": facts
            }) if (citations or facts) else "No news snippets available."
            
            memories = memory_data.get(ev_id, [])
            memory_str = "\n".join([f"- (Sim: {m['similarity']}) {m['lesson']}" for m in memories]) if memories else "No relevant historical lessons found."
            
            matchups_data.append({
                "event_id": ev_id,
                "matchup": f"{ev.away_team} at {ev.home_team}",
                "quantitative_data": quant,
                "evidence": evidence_str,
                "historical_lessons": memory_str
            })

        system_prompt = f"""
        You are 'The Oracle', a meta-agent overseeing a council of specialized AI sports betting algorithms.
        You are evaluating a batch of {len(events)} college basketball matchups.
        
        Here is the FACTUAL DATA gathered for each matchup:
        {json.dumps(matchups_data, indent=2)}
         
        TASK:
        1. For EACH matchup, analyze the `evidence` section. Use `extracted_facts` for verifiable roster/injury claims; use `raw_snippets` for broader context only.
        2. Combine these facts with the `quantitative_data` and `historical_lessons`.
        3. CRITICAL: Pay special attention to `historical_lessons`. If the system has repeatedly missed on a specific team or matchup archetype, apply a qualitative correction and flag it in red_flags.
        4. Provide strictly data-backed executive summaries and final verdicts.
        5. Emit `signals.red_flags` for any major risks, contradictions, or recurring lesson patterns that require human review.
        
        ANTI-HALLUCINATION INSTRUCTIONS:
        - Do NOT invent storylines or unverified dynamics.
        - If no actionable news is in the snippets, state "No actionable news found" and rely on the quantitative data + historical lessons.
        - You MUST explicitly evaluate Spread, Moneyline, and Game Totals.
        
        OUTPUT FORMAT MUST BE VALID JSON:
        Return a single dictionary where keys are the exact `event_id` strings.
        Each entry must include a "debate" with these five specific agent roles:
        - "Executive Summary": High-level view combining quant edge + news context.
        - "Research & Roster": Factual news and injury analysis from extracted_facts only.
        - "Historical Context": Deep dive into historical_lessons and how they apply here.
        - "Contrarian Auditor": A summary of the contrarian critique, risks, and misinterpretations.
        - "Verdict": Final synthesizing decision across Spread, Moneyline, and Totals.
        {{
            "event_id_1": {{
                "debate": [
                    {{"agent": "Executive Summary", "message": "..."}},
                    {{"agent": "Research & Roster", "message": "..."}},
                    {{"agent": "Historical Context", "message": "..."}},
                    {{"agent": "Contrarian Auditor", "message": "..."}},
                    {{"agent": "Verdict", "message": "..."}}
                ],
                "oracle_verdict": "...",
                "signals": {{
                    "confidence": 0.0,
                    "market_lean": {{
                        "spread": {{"side": "HOME|AWAY|NONE", "points": 0.0, "reason": ""}},
                        "total": {{"side": "OVER|UNDER|NONE", "points": 0.0, "reason": ""}},
                        "moneyline": {{"side": "HOME|AWAY|NONE", "reason": ""}}
                    }},
                    "data_points": [
                        {{"type": "injury|rotation|travel|fatigue|matchup|pace|other", "team": "", "detail": "", "source_url": ""}}
                    ],
                    "sources": ["https://..."],
                    "red_flags": ["<brief description of any major risk or contradiction, or \\"\\" if none>"]
                }}
            }}
        }}
        """

        fast_mode = bool(context.get("fast_mode"))
        llm_model = "gemini-2.5-flash-lite" if fast_mode else "gemini-2.0-flash"

        try:
            self.log_trace(
                f"Pass 1: Initial Synthesis for {len(events)} matchups",
                {"event_ids": [ev.event_id for ev in events], "fast_mode": fast_mode},
            )

            # Pass 1: Initial Debate (includes all 5 roles incl. Contrarian Auditor)
            initial_response = generate_content(
                model=llm_model,
                system_prompt=system_prompt,
                json_mode=True,
                max_tokens=3072 if fast_mode else 8192,
                timeout=18 if fast_mode else 25,
                retries=2 if fast_mode else 3,
            )
            if not initial_response:
                raise ValueError("Oracle Pass 1 returned empty response")

            if fast_mode:
                final_text = initial_response
            else:
                # Pass 2: The Contrarian Critique
                critique_prompt = f"""
            You are the 'Council Auditor', a contrarian sports analyst. 
            Review the following initial AI council debate for {len(events)} matchups:
            
            {initial_response}
            
            TASK:
            1. Identify any "groupthink" or overly optimistic assumptions in the verdicts.
            2. For each matchup, find ONE major risk or contradiction that the initial council ignored.
            3. CRITICAL: If a 'historical_lesson' or 'extracted_fact' was misinterpreted, flag it clearly.
            4. Return a JSON dict keyed by event_id with a concise 'critique' and a 'risk_score' (0.0 to 1.0).
            """

                self.log_trace("Pass 2: Contrarian Critique initiated")
                critique_response = generate_content(
                    model=llm_model,
                    system_prompt=critique_prompt,
                    json_mode=True,
                    max_tokens=4096
                )
                if not critique_response:
                    raise ValueError("Oracle Pass 2 (Critique) returned empty response")

                # Pass 3: Final Synthesis (Injecting Critique back into the Oracle)
                final_prompt = f"""
            You are 'The Oracle'. You have completed an initial debate and received a critique from the Council Auditor.
            
            INITIAL DEBATE:
            {initial_response}
            
            CONTRARIAN CRITIQUE:
            {critique_response}
            
            TASK:
            1. Produce the FINAL councils_narrative JSON.
            2. Integrate the 'Critique' into a new agent role called "Contrarian Auditor" in the debate array. This agent should summarize the auditor's key findings.
            3. Adjust the 'oracle_verdict' and 'signals.confidence' if the critique identified valid risks.
            4. If the critique was insightful, add its points to `signals.red_flags`.
            
            Keep the exact same JSON format as the initial debate, but with the 5th agent "Contrarian Auditor" added to the debate array.
            """

                self.log_trace("Pass 3: Final Synthesis initiated")
                final_text = generate_content(
                    model=llm_model,
                    system_prompt=final_prompt,
                    json_mode=True,
                    max_tokens=8192
                )

                if not final_text:
                    raise ValueError("Oracle Pass 3 (Synthesis) returned empty response")
                
            clean_text = final_text.strip()
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
            clean_text = clean_text.strip()
            
            council_output = json.loads(clean_text)
            
            # Map back to results ensuring all events have an entry
            for ev in events:
                if ev.event_id in council_output:
                    results[ev.event_id] = council_output[ev.event_id]
                    trace_data = {
                        "verdict": results[ev.event_id].get('oracle_verdict'),
                        "confidence": results[ev.event_id].get('signals', {}).get('confidence')
                    }
                    self.log_trace(f"Oracle final verdict generated for {ev.away_team} at {ev.home_team}", trace_data)
                else:
                    results[ev.event_id] = {
                        "debate": [{"agent": "System", "message": "Oracle omitted this event in final synthesis."}],
                        "oracle_verdict": "Omitted.",
                        "signals": {"confidence": 0.0, "data_points": [], "sources": [], "red_flags": []}
                    }

            # Persist structured signals to council_signals table
            self._persist_signals(events, results, run_id)

        except Exception as e:
            print(f"[OracleAgent] Synthesis failed for batch: {e}")
            for ev in events:
                results[ev.event_id] = {
                    "debate": [{"agent": "System", "message": f"Error generating debate: {e}"}],
                    "oracle_verdict": "Could not synthesize due to error.",
                    "signals": {"confidence": 0.0, "data_points": [], "sources": [], "red_flags": []}
                }

        return results

    def _persist_signals(self, events: List[EventContext], results: Dict[str, Any], run_id: str) -> None:
        """
        Write each event's signals to council_signals for offline auditing.
        Idempotent: uses ON CONFLICT DO UPDATE so re-runs are safe.
        """
        if not run_id:
            return  # Can't key the row without a run_id; skip silently

        try:
            from src.database import get_db_connection, _exec

            with get_db_connection() as conn:
                for ev in events:
                    ev_id = ev.event_id
                    nar = results.get(ev_id) or {}
                    signals = nar.get('signals') if isinstance(nar, dict) else None
                    if not signals:
                        continue
                    sources = signals.get('sources') if isinstance(signals, dict) else None
                    _exec(conn, """
                        INSERT INTO council_signals (run_id, event_id, league, signals_json, sources)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (run_id, event_id) DO UPDATE SET
                          signals_json = EXCLUDED.signals_json,
                          sources = EXCLUDED.sources,
                          created_at = NOW()
                    """, (
                        run_id, ev_id, ev.league,
                        json.dumps(signals),
                        json.dumps(sources) if sources is not None else None,
                    ))
                conn.commit()
            print(f"[OracleAgent] Persisted signals for {len(events)} events to council_signals.")
        except Exception as e:
            print(f"[OracleAgent] Signal persistence failed (non-fatal): {e}")
