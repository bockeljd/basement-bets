from typing import List, Dict, Optional
import re
from datetime import datetime

class DraftKingsTextParser:
    def parse(self, content: str) -> List[Dict]:
        """Parse raw copy-pasted text from DraftKings.

        DK copy/paste formats vary. Two common shapes:
        1) "My Bets" dump where each bet block ends with a DK transaction id line.
        2) Multi-bet paste where each bet block *starts* with a DK id line.

        This parser supports both.
        """
        bets: List[Dict] = []

        id_pattern = re.compile(r'^(DK\d+)')
        date_pattern = re.compile(r'([A-Z][a-z]{2} \d{1,2}, \d{4}, \d{1,2}:\d{2}(?::\d{2})? [AP]M)')

        lines = [ln.strip() for ln in (content or '').replace('\r\n', '\n').split('\n') if ln.strip()]
        if not lines:
            return []

        def infer_date(buf: List[str]) -> str:
            """Infer the bet's placed_at timestamp.

            DK often includes multiple timestamps in a single line (e.g. game start + bet placed).
            We prefer the *last* timestamp we can find in the tail of the block.
            """
            raw_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for j in range(1, min(len(buf) + 1, 11)):
                s = buf[-j]
                try:
                    all_matches = date_pattern.findall(s)
                    if all_matches:
                        return all_matches[-1]
                except Exception:
                    pass

                d_match = date_pattern.search(s)
                if d_match:
                    return d_match.group(1)

                if re.search(r"[A-Z][a-z]{2} \d{1,2}, \d{4}", s):
                    return s
            return raw_date

        # Robust block splitting: DK ids often appear inline (no newlines).
        # We split the raw content by DK ids and treat each DK id as the block terminator.
        raw = (content or '').replace('\r\n', '\n')
        raw = raw.replace('\u2212', '-').replace('\u2013', '-').replace('\u2014', '-').replace('\u2212', '-')
        id_inline = re.compile(r'(DK\d{10,})')
        matches = list(id_inline.finditer(raw))
        if matches:
            prev = 0
            for m in matches:
                bet_id = m.group(1)
                block_text = raw[prev:m.start()].strip()
                prev = m.end()
                if not block_text:
                    continue
                # Use any existing newlines; otherwise keep as one line.
                buf = [ln.strip() for ln in block_text.split('\n') if ln.strip()] or [block_text]
                raw_date = infer_date(buf)
                bet = self._parse_block(buf, raw_date, bet_id)
                if bet:
                    bets.append(bet)
            # Ignore trailing text after last DK id (usually empty)
            return bets

        # Detect if DK ids are used as START markers (common for multi-bet paste)
        first_id_idx = None
        for idx, ln in enumerate(lines):
            if id_pattern.search(ln):
                first_id_idx = idx
                break

        start_marker_mode = (first_id_idx is not None and first_id_idx <= 2)

        if start_marker_mode:
            current_id = None
            buf: List[str] = []

            for ln in lines:
                m = id_pattern.search(ln)
                if m:
                    # finalize previous
                    if buf and current_id:
                        raw_date = infer_date(buf)
                        bet = self._parse_block(buf, raw_date, current_id)
                        if bet:
                            bets.append(bet)
                    # start new
                    current_id = m.group(1)
                    buf = []
                    continue

                buf.append(ln)

            # trailing
            if buf:
                raw_date = infer_date(buf)
                bet = self._parse_block(buf, raw_date, current_id or 'DK_UNKNOWN')
                if bet:
                    bets.append(bet)

            return bets

        # Default: END marker mode (DK id ends a block)
        buffer: List[str] = []
        for ln in lines:
            m = id_pattern.search(ln)
            if m:
                bet_id = m.group(1)
                if buffer:
                    raw_date = infer_date(buffer)
                    bet = self._parse_block(buffer, raw_date, bet_id)
                    if bet:
                        bets.append(bet)
                buffer = []
            else:
                buffer.append(ln)

        # trailing block without id
        if buffer:
            raw_date = infer_date(buffer)
            bet = self._parse_block(buffer, raw_date, bet_id='DK_UNKNOWN')
            if bet:
                bets.append(bet)

        return bets


    def _parse_block(self, lines: List[str], date_str: str, bet_id: str) -> Optional[Dict]:
        try:
            # 0. Pre-filter Noise
            filter_patterns = [
                r'^\d+$', # Single numbers (scorecard)
                r'^Final Score', 
                r'^View Picks',
                r'^\w{3} \d{1,2}, \d{4}', # Date inside block
                r'Parlay Boost',
                r'^\+\d+%\s+BOOST$',
                r'^BOOST$',
                r'^T$', # Single T from scorecard
                r'^Paste Bet Slip',
                r'^Sportsbook',
                r'^Bankroll Account',
                r'^Main Bankroll',
                r'^Paste Slip Text',
                r'^Review Details',
                r'^DraftKings$',
                # DK live market labels
                r'^Live\s+Spread$',
                r'^Live\s+Total$',
                r'^Live\s+Money\s*line$',
                r'^Live\s+Moneyline$',
            ]
            
            cleaned_lines = []
            for l in lines:
                 l = l.strip()
                 if not l: continue
                 # Normalize dashes
                 l = l.replace('\u2212', '-').replace('\u2013', '-').replace('\u2014', '-')
                 
                 is_noise = False
                 for p in filter_patterns:
                     if re.search(p, l): is_noise = True; break
                 
                 if ("Wager:" in l or "Paid:" in l or "Payout:" in l):
                     is_noise = False # Always keep financial lines
                     
                 if not is_noise:
                     cleaned_lines.append(l)
            
            lines = cleaned_lines
            if not lines: return None

            # 1. Identify Lines by Content
            status = "PENDING"
            status_idx = -1
            wager = 0.0
            paid = 0.0
            wager_idx = -1
            matchup = ""
            matchup_idx = -1
            paid_idx = -1
            header = ""
            header_idx = -1
            odds = None

            # Compact one-line DK paste support (common on mobile):
            # Example:
            #   Tennessee State -3.5-108 Spread Won Wager: $10.00Paid: $19.25 ... Final Score Feb 19, 2026, ... DK...
            text_one = " ".join([str(x) for x in (lines or [])]).strip()
            text_one = text_one.replace('\u2212', '-').replace('\u2013', '-').replace('\u2014', '-')
            compact = re.search(
                r"^(?P<team>.+?)\s+(?P<line>[+-]\d+(?:\.\d+)?)\s*(?P<odds>[+-]\d{3,})\s+(?P<mkt>SPREAD|TOTAL|MONEYLINE|ML)\s+(?P<status>WON|LOST|PUSH|CASHED\s+OUT)\b",
                text_one,
                re.IGNORECASE,
            )

            for i, l in enumerate(lines):
                # Normalize dashes to standard hyphen (Already done above, but safe to keep or remove)
                l_up = l.upper()
                
                # Odds / Header (PARLAY, SGP, Pick, ML, OR [+-]\d{3,})
                # We enforce 3+ digits for odds to avoid matching spread points like -2.5
                if header_idx == -1:
                    odds_matches = re.findall(r'[+-]\d{3,}', l)
                    keywords = ["PARLAY", "SGP", "PICK", "ML", "MONEYLINE", "STRAIGHT", "LEG", "SPREAD", "TOTAL", "OVER", "UNDER", "PROP", "TEASER", "ROUND ROBIN"]
                    if odds_matches or any(x in l_up for x in keywords):
                        header = l
                        header_idx = i
                        if odds_matches:
                            # If both boosted (+...) and regular (-...) odds appear, prefer boosted odds.
                            # DK often shows something like "-110+118" where +118 is the boosted payout.
                            try:
                                poss = [o for o in odds_matches if o.startswith('+')]
                                pick = poss[-1] if poss else odds_matches[-1]
                                odds = int(pick)
                            except Exception:
                                odds = int(odds_matches[-1])

                # Status
                if status == "PENDING" and any(x in l_up for x in ["WON", "LOST", "CASHED OUT"]):
                    if "WON" in l_up: status = "WON"
                    elif "LOST" in l_up: status = "LOST"
                    elif "CASHED OUT" in l_up: status = "CASHED OUT"
                    status_idx = i
                
                # Wager
                if "Wager:" in l:
                    w_match = re.search(r'Wager:[\s\xa0]*\$([\d\.,]+)', l)
                    if w_match: wager = float(w_match.group(1).replace(',', ''))
                    wager_idx = i
                
                # Paid/Payout on any line
                p_match = re.search(r'(?:Paid|Payout):[\s\xa0]*\$([\d\.,]+)', l)
                if p_match:
                    paid = float(p_match.group(1).replace(',', ''))
                    paid_idx = i

            # Matchup & Team Detection
            teams_found = []

            # Team Keywords — use shared sport detection module
            from src.parsers.sport_detection import detect_sport, NCAAM_TEAMS, NFL_TEAMS, NBA_TEAMS, MLB_KEYWORDS, NHL_KEYWORDS, SOCCER_KEYWORDS
            all_team_keywords = NCAAM_TEAMS + NFL_TEAMS + NBA_TEAMS + MLB_KEYWORDS + NHL_KEYWORDS + SOCCER_KEYWORDS

            # If we have a compact header match, pre-seed obvious fields early.
            compact_team = None
            compact_line = None
            compact_mkt = None
            compact_status = None
            if compact:
                try:
                    compact_team = compact.group('team').strip()
                    compact_line = float(compact.group('line'))
                    odds = int(compact.group('odds'))
                    compact_mkt = compact.group('mkt').strip().upper()
                    compact_status = compact.group('status').strip().upper().replace(' ', '_')
                    if compact_status == 'CASHED_OUT':
                        status = 'CASHED OUT'
                    else:
                        status = compact_status
                    status_idx = 0
                except Exception:
                    pass

            for i, l in enumerate(lines):
                l_lower = l.lower()
                # Existing Matchup Check
                if matchup_idx == -1 and ("@" in l or " vs " in l_lower or " v " in l_lower):
                    matchup = l
                    matchup_idx = i

                # Team Scanning (if no typical matchup line found)
                for t in all_team_keywords:
                    if t in l_lower and len(t) > 3:  # Avoid short noise
                        # Store the actual team name (title cased), not the full line
                        team_name = t.title()
                        if team_name not in teams_found:
                            teams_found.append(team_name)
                        break  # Only capture first team match per line to avoid duplicates

            # 2. Bet Type Normalization
            # Note: DK dumps sometimes contain leg-level lines that are not standalone bets.
            # We treat them as artifacts and try not to surface them as "Leg" bet_type.
            # PRIORITY: Check for explicit bet type keywords on their own lines FIRST
            explicit_bet_type = None

            # If compact header tells us the market, lock bet_type from that.
            if compact_mkt:
                if compact_mkt == 'SPREAD':
                    explicit_bet_type = 'Spread'
                elif compact_mkt in ('TOTAL',):
                    explicit_bet_type = 'Over/Under'
                elif compact_mkt in ('MONEYLINE', 'ML'):
                    explicit_bet_type = 'ML'

            # If DK paste is the newline format but lacks the word "Spread"/"Total" in the header,
            # infer market type from the first *selection-like* line shape.
            # Important: DK pastes often start with financial lines like "Wager: $50".
            candidate_lines = [ln.strip() for ln in lines if ln and not re.search(r'^(Wager:|Paid:|Payout:)', ln, re.IGNORECASE)]
            first_line = (candidate_lines[0] if candidate_lines else '').strip()
            if not explicit_bet_type and first_line:
                # Total like: OVER 165.5-115+113
                if re.match(r'^(OVER|UNDER)\s+\d+(?:\.\d+)?', first_line, re.IGNORECASE):
                    explicit_bet_type = 'Over/Under'
                # Spread like: KANSAS -4.5 (-110)
                elif re.match(r'^.+\s+[+-]\d+(?:\.\d+)?', first_line):
                    explicit_bet_type = 'Spread'
                # Moneyline like: XAVIER+114 or MICHIGAN+200+260
                elif re.match(r'^.+[+-]\d{3,}(?:[+-]\d{3,})?$', first_line):
                    explicit_bet_type = 'ML'
            explicit_bet_type_keywords = {
                "SPREAD": "Spread", "POINT SPREAD": "Spread",
                "MONEYLINE": "ML", "MONEY LINE": "ML", "ML": "ML",
                "TOTAL": "Over/Under", "OVER/UNDER": "Over/Under", "OVER / UNDER": "Over/Under",
                "OVER": "Over/Under", "UNDER": "Over/Under",
                "PROP": "Prop", "PLAYER PROP": "Prop",
                "SGP": "SGP", "SAME GAME PARLAY": "SGP",
                "PARLAY": "Parlay", "2 LEG": "2 leg parlay", "3 LEG": "3 leg parlay", "4+ LEG": "4+ leg parlay",
            }
            for l in lines:
                l_stripped = l.strip().upper()
                if l_stripped in explicit_bet_type_keywords:
                    explicit_bet_type = explicit_bet_type_keywords[l_stripped]
                    break
            
            # If we found an explicit keyword, use it. Otherwise, fall back to header parsing.
            if explicit_bet_type:
                bet_type = explicit_bet_type
            else:
                bet_type_raw = header if header else "Straight"
                bet_type = bet_type_raw
                # Remove odds from bet type
                # Handle concatenated odds in header like "SGP2 Picks+100+130" -> extract +130
                odds_matches = re.findall(r'[+-]\d{3,}', bet_type)
                if odds_matches:
                     # If both boosted (+...) and regular (-...) odds appear, prefer boosted odds.
                     try:
                         poss = [o for o in odds_matches if o.startswith('+')]
                         pick = poss[-1] if poss else odds_matches[-1]
                         odds = int(pick)
                     except Exception:
                         try:
                             odds = int(odds_matches[-1])
                         except Exception:
                             pass
                     for o in odds_matches:
                         bet_type = bet_type.replace(o, "")
                bet_type = bet_type.strip()
                
                bet_type_upper = bet_type.upper()
                
                # Check SGP in header
                if "SGP" in bet_type_upper or "SAME GAME PARLAY" in bet_type_upper:
                    # Keep leg count if available
                    leg_match = re.search(r'(\d+)', bet_type_upper)
                    if leg_match:
                         bet_type = f"{leg_match.group(1)} Leg SGP"
                    else:
                         bet_type = "SGP"
                elif any(x in bet_type_upper for x in ["WINNER (ML)", "STRAIGHT", "MONEYLINE", "MONEY LINE", "ML"]):
                    bet_type = "ML"
                elif any(x in bet_type_upper for x in ["PARLAY", "LEG", "PICK"]):
                    leg_match = re.search(r'(\d+)', bet_type)
                    if leg_match:
                        bet_type = f"{leg_match.group(1)} leg parlay"
                    elif "4+" in bet_type_upper or "4 LEG" in bet_type_upper:
                        bet_type = "4 leg parlay"
                    else:
                        # Avoid returning bare "Leg" (those are usually legs of a parent parlay/SGP)
                        bet_type = "parlay"
                elif any(x in bet_type_upper for x in ["OVER / UNDER", "TOTAL OVER/UNDER", "TOTAL (OVER/UNDER)", "TOTAL", "OVER", "UNDER"]):
                    bet_type = "Over/Under"
                elif "PROP" in bet_type_upper:
                    bet_type = "Prop"
                elif "SPREAD" in bet_type_upper or "POINT SPREAD" in bet_type_upper:
                    bet_type = "Spread"
                else:
                     # Last ditch check if Spread/ML is mentioned in other lines
                     text_all = " ".join(lines).upper()
                     if "SPREAD" in text_all: bet_type = "Spread"
                     elif "MONEYLINE" in text_all: bet_type = "ML"
                     elif "TOTAL" in text_all or "OVER" in text_all: bet_type = "Over/Under"
                     else: bet_type = "Straight" # Default fallback


            # 3. Selection Identification — only team name(s) + bet line
            # Aggressively filter: no odds, no bet type labels, no scores, no noise
            selection_noise_patterns = [
                r'^\d+$',                    # Single numbers (scorecard)
                r'^Final Score',
                r'^View Picks',
                r'^\w{3} \d{1,2}, \d{4}',   # Date inside block
                r'Parlay Boost',
                r'^\+\d+%\s+BOOST$',
                r'^BOOST$',
                r'^T$',
                r'^Paste Bet Slip',
                r'^Sportsbook',
                r'^Bankroll Account',
                r'^Main Bankroll',
                r'^Paste Slip Text',
                r'^Review Details',
                r'^DraftKings$',
                r'^Outcome:',
                r'^My Bets',
                r'^Includes:',
                r'^Cash Out:',
                r'^Potential Payout:',
                r'^vs$',
                r'^Share',
                r'^DraftKings Brand',
                r'^Icon representing',
                r'^\d+ Picks',
                r'^Information$',
                r'^Down$',
                r'^KING OF THE ENDZONE$',
                r'^Finished$',
                r'^Final$',
                # DK live market labels (not selections)
                r'^Live\s+Spread$',
                r'^Live\s+Total$',
                r'^Live\s+Money\s*line$',
                r'^Live\s+Moneyline$',
                r'Wager:',
                r'Paid:',
                r'Payout:',
                r'^\$',                      # Dollar amounts
            ]
            # Bet type labels to exclude from selection
            bet_type_labels_upper = [
                "WINNER (ML)", "ML", "MONEYLINE", "MONEY LINE",
                "SPREAD", "POINT SPREAD", "SPREAD BETTING",
                "TOTAL", "TOTAL (OVER/UNDER)", "TOTAL OVER/UNDER",
                "OVER / UNDER", "OVER/UNDER", "OVER", "UNDER",
                "STRAIGHT", "PROP", "PLAYER PROP",
                "SGP", "SAME GAME PARLAY", "PARLAY",
                "TEASER", "ROUND ROBIN", "PICK",
            ]
            
            selection_parts = []
            for i, l in enumerate(lines):
                if i in [header_idx, status_idx, wager_idx, matchup_idx, paid_idx]:
                    continue
                
                # Filter noise patterns
                is_noise = False
                for p in selection_noise_patterns:
                    if re.search(p, l):
                        is_noise = True
                        break
                if is_noise:
                    continue
                
                # Filter bet type labels (exact match, case-insensitive)
                l_upper = l.strip().upper()
                if l_upper in bet_type_labels_upper:
                    continue

                # Filter standalone odds (3+ digits with sign, e.g. +150, -110)
                if re.match(r'^[+-]\d{3,}$', l.strip()):
                    continue

                # Filter lines that are ONLY a keyword embedded in longer text like "2 Picks"
                if re.match(r'^\d+\s+(Picks|Legs?)$', l.strip(), re.IGNORECASE):
                    continue
                
                selection_parts.append(l)
            
            # Build selection: combine team name with spread/total line
            selection = ""

            # Prefer parsing from the DK first line for the common newline format:
            #   UNDER 165.5-110
            #   MICHIGAN STATE +9.5-110+118
            #   XAVIER+114
            # Prefer first selection-like line (skip financial lines like 'Wager: $50')
            sel_lines = [ln.strip() for ln in lines if ln and not re.search(r'^(Wager:|Paid:|Payout:)', ln, re.IGNORECASE)]
            fl = (sel_lines[0] if sel_lines else '').strip()
            if fl:
                # Total like: UNDER 165.5-115+113
                m = re.match(r'^(OVER|UNDER)\s+(\d+(?:\.\d+)?)', fl, re.IGNORECASE)
                if m:
                    selection = f"{m.group(1).upper()} {m.group(2)}"

                # Spread like: TEAM +9.5-110+118
                if not selection:
                    m = re.match(r'^(.+?)\s+([+-]\d+(?:\.\d+)?)', fl)
                    if m:
                        team = m.group(1).strip()
                        line = m.group(2).strip()
                        # avoid junk headers like SGP2 Picks
                        if team and not re.search(r'\b(PICKS?|SGP|PARLAY)\b', team, re.IGNORECASE):
                            selection = f"{team} {line}"

                # ML like: SAINT LOUIS+105 or MICHIGAN+200+260
                if not selection:
                    m = re.match(r'^(?P<team>.+?)(?P<odds>[+-]\d{3,})(?:[+-]\d{3,})?$', fl)
                    if m:
                        team = m.group('team').strip()
                        if team and not re.search(r'\b(PICKS?|SGP|PARLAY)\b', team, re.IGNORECASE):
                            selection = f"{team} ML"

            if not selection and compact_team and (compact_line is not None) and (compact_mkt == 'SPREAD'):
                # Spread team + line
                selection = f"{compact_team} {compact_line:+.1f}".replace('+', '')
            elif not selection and compact_team and (compact_line is not None) and (compact_mkt in ('TOTAL',)):
                # Total: try to infer side from team text (rare); default to line only
                selection = f"{compact_team} {compact_line:.1f}"
            elif not selection and selection_parts:
                if len(selection_parts) >= 2 and re.match(r'^[+-]?\d+\.?\d*$', selection_parts[1]):
                    # Team + line (e.g. "Ohio State" + "-6.5" → "Ohio State -6.5")
                    selection = f"{selection_parts[0]} {selection_parts[1]}"
                else:
                    selection = selection_parts[0]
            
            # Construct Matchup from detected Teams if implicit
            if not matchup:
                # Prefer last two explicit team lines (DK often lists away then home as ALLCAPS lines)
                try:
                    caps = []
                    noise_caps = {
                        'WAGER', 'PAID', 'PAYOUT', 'FINAL', 'SCORE', 'LIVE', 'TOTAL', 'SPREAD',
                        'WON', 'LOST', 'CASHED', 'OUT', 'BOOST', 'UNDER', 'OVER', 'VIEW', 'PICKS',
                        'OT'
                    }
                    for ln in lines:
                        t = str(ln or '').strip()
                        if not t:
                            continue
                        if re.search(r'(Wager:|Paid:|Payout:)', t, re.IGNORECASE):
                            continue
                        if re.fullmatch(r"[A-Z][A-Z\s\.'\-&]+", t) and len(t) >= 3:
                            if t.upper() in noise_caps:
                                continue
                            if re.fullmatch(r"\+\d+%\s+BOOST", t.upper()):
                                continue
                            caps.append(t)
                    uniq=[]
                    for t in caps:
                        if t not in uniq:
                            uniq.append(t)
                    if len(uniq) >= 2:
                        matchup = f"{uniq[-2].title()} @ {uniq[-1].title()}"
                except Exception:
                    pass

            if not matchup and len(teams_found) >= 2:
                # Use @ convention (away @ home) when we only have two teams; DK score tables often list away then home.
                matchup = f"{teams_found[0]} @ {teams_found[1]}"

            # DK compact paste often provides teams as two adjacent ALLCAPS tokens (e.g., "OHIO MIAMI OH" or "MICHIGAN STATE WISCONSIN")
            if (not matchup or matchup == "Unknown Matchup") and len(teams_found) < 2:
                try:
                    tokens = re.findall(r"\b[A-Z]{3,}(?:\s+[A-Z]{2,})*\b", " ".join(lines))
                    # Remove known noise tokens
                    noise = {
                        'WAGER', 'PAID', 'PAYOUT', 'FINAL', 'SCORE', 'LIVE', 'TOTAL', 'SPREAD',
                        'WON', 'LOST', 'CASHED', 'OUT', 'BOOST', 'UNDER', 'OVER',
                        'INCLUDES', 'POTENTIAL'
                    }
                    cleaned = []
                    for t in tokens:
                        tt = t.strip()
                        if not tt:
                            continue
                        # Strip promo prefix inside the token
                        if tt.upper().startswith('BOOST '):
                            tt = tt[6:].strip()
                        if tt and tt not in noise:
                            cleaned.append(tt)
                    # De-dupe while preserving order
                    uniq = []
                    for t in cleaned:
                        if t not in uniq:
                            uniq.append(t)

                    # Drop promo markers and cleanup
                    uniq = [t for t in uniq if all(x not in t for x in ['+30%', '+25%', '+20%'])]
                    # Remove promo token itself
                    uniq = [t for t in uniq if t.strip().upper() != 'BOOST']
                    uniq = [t.replace('Boost ', '').strip() for t in uniq if t.strip()]

                    if len(uniq) >= 2:
                        # If token 0 looks like "MICHIGAN STATE" and token 1 looks like "MICHIGAN STATE WISCONSIN",
                        # pick the *new* team from token 1.
                        a = uniq[0]
                        b = uniq[1]
                        a_s = str(a).strip()
                        b_s = str(b).strip()
                        if b_s.upper().startswith(a_s.upper() + ' '):
                            rem = b_s[len(a_s):].strip()
                            # opponent may be multi-word; keep first 2 tokens at most
                            rem_parts = [p for p in rem.split() if p]
                            opp = " ".join(rem_parts[:2]) if rem_parts else rem
                            matchup = f"{a_s.title()} vs {opp.title()}"
                        else:
                            matchup = f"{a_s.title()} vs {b_s.title()}"
                    elif len(uniq) == 1:
                        # Single token like "OHIO MIAMI OH" -> split into two teams
                        parts = [p for p in str(uniq[0]).split() if p]
                        if len(parts) >= 2:
                            matchup = f"{parts[0].title()} vs {parts[1].title()}"
                except Exception:
                    pass

            if not matchup:
                matchup = selection or "Unknown Matchup"
            if not selection:
                selection = matchup


            # Fallback Odds Scan
            if odds is None:
                for l in lines:
                    # Look for standalone odds line like "+150", "-110", or "+ 150"
                    # Allow optional space between sign and number
                    odds_scan = re.search(r'^([+-])\s*(\d{3,})$', l.strip())
                    if odds_scan:
                        try:
                             sign = odds_scan.group(1)
                             num = odds_scan.group(2)
                             possible_odds = int(f"{sign}{num}")
                             odds = possible_odds
                             break
                        except: pass

            # 4. Financial fallbacks (DK body dumps often omit explicit Wager:/Paid: lines)
            text_all = " ".join(lines)

            if wager == 0.0:
                m = re.search(r'\$\s*([0-9]+\.[0-9]{2})', text_all)
                if m:
                    try:
                        wager = float(m.group(1))
                    except Exception:
                        pass

            profit = None
            # Look for explicit net result like +$25.40 / -$10.00
            pm = re.search(r'([+-])\$\s*([0-9]+\.[0-9]{2})', text_all)
            if pm:
                try:
                    sign = 1.0 if pm.group(1) == '+' else -1.0
                    profit = sign * float(pm.group(2))
                except Exception:
                    profit = None

            # If we have Paid/Payout, compute profit
            status_up = status.upper()
            if profit is None:
                if status_up in ("WON", "CASHED OUT"):
                    if paid > 0 and wager > 0:
                        profit = paid - wager
                    elif odds and wager > 0:
                        profit = wager * (odds / 100) if odds > 0 else wager * (100 / abs(odds))
                    else:
                        profit = 0.0
                elif status_up == "LOST":
                    profit = -wager
                else:
                    profit = 0.0

            # Description/selection: one-line summary (keep selection details but bounded)
            # Prefer matchup; then selection; keep it concise.
            base = matchup or selection or "Unknown"
            summary = base
            if odds is not None:
                summary = f"{bet_type} {odds}: {base}"
            else:
                summary = f"{bet_type}: {base}"

            # Hard cap to keep UI sane
            if len(summary) > 140:
                summary = summary[:137] + "..."
            
            # Date parse (avoid python-dateutil dependency in serverless)
            dt = None
            try:
                date_str_clean = str(date_str).split('\n')[0].strip()
                dt = datetime.strptime(date_str_clean, "%b %d, %Y, %I:%M:%S %p")
            except Exception:
                dt = None

            if dt is None:
                # fallback: parse "Feb 9, 2026" without time
                try:
                    m = re.search(r"([A-Z][a-z]{2} \d{1,2}, \d{4})", str(date_str))
                    if m:
                        dt = datetime.strptime(m.group(1), "%b %d, %Y")
                except Exception:
                    dt = None

            if dt is None:
                dt = datetime.now()
            
            description = summary

            # 5. Sport Inference — use shared detector
            sport = detect_sport(" ".join(lines) + " " + selection + " " + matchup)

            # Guardrails: skip only truly malformed artifacts.
            # For DK paste dumps, we prefer returning a minimal row over dropping
            # the bet entirely (dropping causes missed bets + duplicates later).
            if wager is None or float(wager) <= 0:
                return None

            # Ensure we always keep an external_id when DK id is present.
            ext_id = bet_id if bet_id and bet_id != 'DK_UNKNOWN' else None

            # If selection couldn't be inferred, fall back to a trimmed version of the summary.
            if not selection or str(selection).strip().lower() in ('unknown matchup', 'unknown'):
                selection = (matchup or summary or 'DraftKings bet')
                try:
                    selection = str(selection).strip()
                except Exception:
                    selection = 'DraftKings bet'

            return {
                "provider": "DraftKings",
                "external_id": ext_id,
                "date": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "sport": sport,
                "bet_type": bet_type,
                "wager": wager,
                "profit": round(profit, 2),
                "status": status.upper(),
                "description": description,
                "selection": selection,
                "odds": odds,
                "is_live": "LIVE" in " ".join(lines).upper(),
                "is_bonus": "Boost" in "".join(lines) or "Bonus" in "".join(lines),
                "raw_text": "\n".join(lines) + f"\n{date_str}{bet_id}"
            }
            
        except Exception as e:
            print(f"Error parsing block: {e}")
            return None
