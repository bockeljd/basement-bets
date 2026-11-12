import os
import json
import math
from typing import Any, Dict, List, Optional
from src.utils.gemini_rest import embed_content

from src.agents.base import BaseAgent
from src.agents.contracts import EventContext
from src.database import get_db_connection, _exec

class MemoryAgent(BaseAgent):
    """
    RAG (Retrieval-Augmented Generation) Agent for historical post-mortem retrieval.
    Queries the 'agent_memories' table via cosine similarity on embeddings.
    """
    def __init__(self):
        super().__init__()

    def execute(self, context: Dict[str, Any], *args, **kwargs) -> Dict[str, Any]:
        """
        Expects a list of events. Returns a dict mapping event_id -> list of lessons learned.
        """
        events: List[EventContext] = context.get("events", [])
        if not events:
            return {}

        retrieved_memories = {}
        
        # For serverless environments without pgvector, we load memories and compute cosine similarity in python
        # Since memories are sparse (only games we bet on), this is extremely fast.
        all_memories = self._load_all_memories()
        
        if not all_memories:
            self.log_trace("No memories found in database. Skipping RAG.")
            for ev in events:
                retrieved_memories[ev.event_id] = []
            return retrieved_memories

        # No need for matrix creation in pure python
        # We will iterate through all_memories directly
        
        fast_mode = bool(context.get("fast_mode"))
        for ev in events:
            # Multi-query strategy offline; single composite query in fast serverless mode.
            if fast_mode:
                queries = [
                    f"Lessons learned betting on {ev.away_team} vs {ev.home_team} basketball matchups injuries tempo",
                ]
            else:
                queries = [
                    f"Lessons learned betting on {ev.away_team} vs {ev.home_team} tight matchups",
                    f"Lessons learned betting on {ev.away_team} performance and dynamics",
                    f"Lessons learned betting on {ev.home_team} performance and dynamics",
                    f"Historical betting lessons for high-tempo or defensive matchups similar to {ev.away_team} style",
                    f"Historical betting lessons for high-tempo or defensive matchups similar to {ev.home_team} style"
                ]
            
            event_lessons = []
            seen_ids = set()

            for query in queries:
                self.log_trace(f"Performing RAG retrieval for {ev.event_id}", {"query": query})
                try:
                    # 1. Embed the target query
                    target_emb = embed_content(
                        model="models/gemini-embedding-001",
                        content=query,
                        task_type="RETRIEVAL_QUERY"
                    )
                    
                    # 2. Compute cosine similarities (dot product)
                    scored_memories = []
                    for mem in all_memories:
                        emb = mem['embedding']
                        dot_product = sum(a * b for a, b in zip(emb, target_emb))
                        scored_memories.append((dot_product, mem))
                    
                    # 3. Sort by similarity descending
                    scored_memories.sort(key=lambda x: x[0], reverse=True)
                    
                    for similarity, mem in scored_memories[:3]:
                        # Lower threshold for team-specific search to catch relevant history
                        threshold = 0.62 if "performance" in query else 0.65
                        if similarity > threshold:
                            mem_id = f"{mem['team_a']}_{mem['team_b']}_{mem['timestamp']}"
                            if mem_id not in seen_ids:
                                seen_ids.add(mem_id)
                                self.log_trace(f"Retrieved relevant memory ({round(float(similarity), 3)})", {
                                    "source_matchup": f"{mem['team_a']} vs {mem['team_b']}",
                                    "lesson": mem['lesson']
                                })
                                event_lessons.append({
                                    "similarity": round(float(similarity), 3),
                                    "teams": f"{mem['team_a']} vs {mem['team_b']}",
                                    "lesson": mem['lesson'],
                                    "date": mem['timestamp']
                                })
                except Exception as e:
                    self.log_trace(f"RAG query failed for {ev.event_id}", {"query": query, "error": str(e)})

            # Sort all retrieved lessons for this event by similarity
            event_lessons.sort(key=lambda x: x['similarity'], reverse=True)
            retrieved_memories[ev.event_id] = event_lessons[:6] # Top 6 from all queries

        return retrieved_memories
        
    def _load_all_memories(self) -> List[Dict]:
        """Loads all memories from DB."""
        try:
            with get_db_connection() as conn:
                # Ensure the table exists
                cur = _exec(conn, "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'agent_memories')")
                exists = cur.fetchone()[0]
                if not exists:
                    return []
                    
                rows = _exec(conn, "SELECT team_a, team_b, lesson, timestamp, embedding_json FROM agent_memories").fetchall()
                memories = []
                for r in rows:
                    if r['embedding_json']:
                        memories.append({
                            'team_a': r['team_a'],
                            'team_b': r['team_b'],
                            'lesson': r['lesson'],
                            'timestamp': str(r['timestamp']),
                            'embedding': json.loads(r['embedding_json'])
                        })
                return memories
        except Exception as e:
            print(f"[MemoryAgent] Could not load memories: {e}")
            return []
