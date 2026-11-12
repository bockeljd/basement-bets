import json
import requests
from bs4 import BeautifulSoup
from typing import Any, Dict, List
from src.agents.base import BaseAgent
from src.agents.contracts import EventContext
from src.utils.gemini_rest import generate_content

class ResearchAgent(BaseAgent):
    """
    Performs real-time web research for an event to find breaking news,
    injuries, or lineup changes, then extracts concrete structured facts
    with source URLs for use by the Agent Council.
    """
    def __init__(self):
        super().__init__()

    def execute(self, context: Dict[str, Any], *args, **kwargs) -> Dict[str, Any]:
        events: List[EventContext] = context.get("events", [])
        if not events:
            return {}

        research_results = {}
        
        # DDG HTML search URL
        search_url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) width/1920",
        }
        
        from src.utils.ncaam_season import current_ncaam_calendar_year
        search_year = current_ncaam_calendar_year()
        batch_citations = {}
        fast_mode = bool(context.get("fast_mode"))
        ddg_timeout = 4 if fast_mode else 10
        for ev in events:
            query = f"{ev.away_team} vs {ev.home_team} basketball news injuries {search_year}"
            self.log_trace(f"Searching DuckDuckGo for {ev.away_team} vs {ev.home_team}", {"query": query})
            try:
                resp = requests.post(search_url, data={"q": query}, headers=headers, timeout=ddg_timeout)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, 'html.parser')

                citations = []
                for res_el in soup.select('.result')[:5]:
                    a = res_el.select_one('a.result__a')
                    sn = res_el.select_one('.result__snippet')
                    if not a:
                        continue
                    url = a.get('href')
                    title = a.get_text(strip=True)
                    snippet = sn.get_text(strip=True) if sn else ''
                    if url and title:
                        citations.append({
                            'title': title,
                            'url': url,
                            'snippet': snippet
                        })
                        self.log_trace(f"Found search result: {title}", {"url": url})

                batch_citations[ev.event_id] = citations
                
                # In serverless fast_mode, rely on snippets to fit strict HTTP budgets.
                scraped_context = []
                if not fast_mode:
                    for cite in citations[:3]:
                        url = cite['url']
                        try:
                            self.log_trace(f"Deep scraping: {url}")
                            c_resp = requests.get(url, headers=headers, timeout=5)
                            c_resp.raise_for_status()
                            c_soup = BeautifulSoup(c_resp.text, 'html.parser')
                            
                            # Remove script/style noise
                            for script in c_soup(["script", "style"]):
                                script.decompose()
                                
                            text = c_soup.get_text(separator=' ', strip=True)
                            # Cap at 1500 chars per page to avoid token blowup
                            scraped_context.append({
                                "url": url,
                                "content": text[:1500]
                            })
                        except Exception as ce:
                            self.log_trace(f"Scrape failed for {url}: {ce}")

                research_results[ev.event_id] = {
                    "query": query,
                    "articles_found": len(citations),
                    "summary": f"Found {len(citations)} raw search results for analysis.",
                    "citations": citations,
                    "deep_context": scraped_context,
                    "facts": []
                }
            except Exception as e:
                print(f"[ResearchAgent] Failed to search for {ev.event_id}: {e}")
                research_results[ev.event_id] = {
                    "query": query,
                    "articles_found": 0,
                    "summary": f"Search failed: {str(e)}",
                    "citations": [],
                    "deep_context": [],
                    "facts": []
                }


        # 2. LLM EXTRACTION — extract structured facts from snippets in a single batched call.
        # Each fact must have: team, type (injury|lineup|travel|pace|other), detail, source_url.
        # Falls back gracefully if the call fails to avoid blocking the Oracle.
        events_with_citations = [ev for ev in events if batch_citations.get(ev.event_id)]
        if events_with_citations and not fast_mode:
            try:
                extraction_input = []
                for ev in events_with_citations:
                    cites = batch_citations.get(ev.event_id, [])
                    deep = research_results[ev.event_id].get("deep_context", [])
                    extraction_input.append({
                        "event_id": ev.event_id,
                        "matchup": f"{ev.away_team} at {ev.home_team}",
                        "snippets": cites,
                        "deep_context": deep
                    })

                extract_prompt = f"""
You are a sports reporter extracting ONLY verifiable facts from search result snippets and scraped article context.

Here is raw research data for multiple college basketball matchups:
{json.dumps(extraction_input, indent=2)}

For EACH matchup, extract concrete facts. Return ONLY a JSON dict keyed by event_id.
Each value is a list of facts with this exact schema:
{{
    "event_id_1": [
      {{"team": "<team name>", "type": "<injury|lineup|travel|fatigue|pace|matchup|other>",
        "detail": "<one sentence, specific and factual>", "source_url": "<URL from snippet or ''>"}}
    ],
    "event_id_2": []
}}

RULES:
- Only include claims directly stated in the snippets or content. NO INFERENCE.
- If no concrete facts exist for a matchup, return an empty list for that event_id.
- Do NOT invent injuries or roster changes.
- Keep detail to one sentence.
"""
                raw = generate_content(
                    model="gemini-2.0-flash",
                    system_prompt=extract_prompt,
                    json_mode=True,
                    max_tokens=2048
                )
                if not raw:
                    extracted = {}
                else:
                    clean = raw.strip()
                    if clean.startswith("```json"):
                        clean = clean[7:]
                    if clean.endswith("```"):
                        clean = clean[:-3]
                    extracted = json.loads(clean.strip())

                for ev in events_with_citations:
                    eid = ev.event_id
                    facts = extracted.get(eid, [])
                    if isinstance(facts, list):
                        research_results[eid]["facts"] = facts
                        count = len(facts)
                        research_results[eid]["summary"] = (
                            f"Found {research_results[eid]['articles_found']} snippets; "
                            f"extracted {count} concrete fact{'s' if count != 1 else ''}."
                        )
                        for f in facts:
                            self.log_trace(
                                f"Extracted fact for {ev.away_team} @ {ev.home_team}: {f.get('detail', '')[:80]}",
                                {"team": f.get("team"), "type": f.get("type"), "url": f.get("source_url")}
                            )

            except Exception as e:
                print(f"[ResearchAgent] LLM fact extraction failed (non-fatal): {e}")
                for ev in events_with_citations:
                    research_results[ev.event_id]["summary"] = (
                        f"Found {research_results[ev.event_id]['articles_found']} raw results; "
                        f"fact extraction unavailable ({type(e).__name__})."
                    )

        return research_results
