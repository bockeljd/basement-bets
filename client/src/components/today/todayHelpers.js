/**
 * Shared formatting, lookup, and plain-English explanation helpers for the Today Dashboard.
 */

export const getTodayEtStr = () =>
  new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });

export const shiftEtDateStr = (dateStr, deltaDays) => {
  try {
    const [yy, mm, dd] = String(dateStr || '').split('-').map((x) => parseInt(x, 10));
    if (!yy || !mm || !dd) return dateStr;
    const base = Date.UTC(yy, mm - 1, dd, 12, 0, 0);
    const next = new Date(base + Number(deltaDays) * 86400000);
    const y = next.getUTCFullYear();
    const m = String(next.getUTCMonth() + 1).padStart(2, '0');
    const d = String(next.getUTCDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
  } catch {
    return dateStr;
  }
};

export const fmtTimeEt = (ts) => {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      timeZone: 'America/New_York',
    });
  } catch {
    return '—';
  }
};

export const fmtSigned = (n, decimals = 1) => {
  if (n === null || n === undefined || n === '') return '—';
  const x = Number(n);
  if (!Number.isFinite(x)) return String(n);
  const s = decimals >= 0 ? x.toFixed(decimals) : String(x);
  return x > 0 ? `+${s}` : s;
};

export const fmtOdds = (price) => {
  if (price === null || price === undefined || price === '') return '—';
  const n = Number(price);
  if (!Number.isFinite(n) || n === 0) return '—';
  return n > 0 ? `+${Math.round(n)}` : `${Math.round(n)}`;
};

export const fmtPct = (decimalVal, decimals = 1) => {
  if (decimalVal === null || decimalVal === undefined || decimalVal === '') return '—';
  const n = Number(decimalVal);
  if (!Number.isFinite(n)) return '—';
  return `${(n * 100).toFixed(decimals)}%`;
};

export const safeReasonText = (rawReason) => {
  if (!rawReason) return '';
  const text = String(rawReason).trim();
  if (!text) return '';
  if (
    text.includes('JSON serializable') ||
    text.includes('Traceback') ||
    text.includes('psycopg2') ||
    text.includes('TypeError')
  ) {
    return 'Analysis temporarily unavailable — open Details to retry';
  }
  if (text.startsWith('Sanity block')) {
    return 'Held for safety — model and sportsbook odds need a closer match';
  }
  if (text.startsWith('Steam move')) {
    return 'Passed — the betting line already moved against this side';
  }
  if (text === 'No Edge Detected') {
    return 'Line matches fair value — pass';
  }
  return text;
};

export const makeMatchupKey = (dayEt, away, home) => {
  const norm = (s) =>
    String(s || '')
      .toLowerCase()
      .replace(/[^a-z0-9]/g, '');
  if (!dayEt || !away || !home) return '';
  return `${dayEt}|${norm(away)}|${norm(home)}`;
};

export const lookupTopPickForGame = (game, rowTopPicks = {}, rowTopPicksByKey = {}) => {
  if (!game) return null;
  if (rowTopPicks[game.id]) return rowTopPicks[game.id];
  const day = game.day_et || (game.start_time ? String(game.start_time).slice(0, 10) : '');
  const k = makeMatchupKey(day, game.away_team, game.home_team);
  return k ? rowTopPicksByKey[k] || null : null;
};

export const normalizeMovementTag = (tag) => {
  const t = String(tag || '').toLowerCase();
  if (t === 'rlm_confirmed') return { label: 'Sharp Money (Line Move)', tone: 'emerald' };
  if (t === 'sharp_backing') return { label: 'Big Money Backing', tone: 'emerald' };
  if (t === 'injury_line_adjusted') return { label: 'Injury Adjustment', tone: 'amber' };
  if (t === 'contra_sharp_money') return { label: 'Against Big Money', tone: 'rose' };
  if (t === 'steam_warning') return { label: 'Line Moving Fast', tone: 'amber' };
  return { label: String(tag || '').replace(/_/g, ' '), tone: 'slate' };
};

export const getRecEv = (rec) => {
  if (!rec) return null;
  const raw = rec.ev ?? rec.ev_raw ?? rec.expected_value ?? rec.ev_per_unit;
  if (raw !== null && raw !== undefined && raw !== '') {
    const n = Number(raw);
    if (Number.isFinite(n)) return Math.abs(n) > 1.5 ? n / 100 : n;
  }
  if (typeof rec.edge === 'string' && rec.edge.includes('%')) {
    const parsed = parseFloat(rec.edge.replace('%', '').trim());
    if (Number.isFinite(parsed)) return parsed / 100;
  }
  return null;
};

export const getConfidenceMeta = (rec) => {
  if (!rec) {
    return { tier: 'LOW', score: null, sortScore: -1, badgeCls: 'bg-slate-800 text-slate-300 border-slate-700' };
  }
  const rawTier = String(
    rec.confidence_tier || (typeof rec.confidence === 'string' ? rec.confidence : '') || ''
  )
    .trim()
    .toUpperCase();
  const rawScore = Number(
    rec.confidence_0_100 ??
      rec.confidence_score ??
      (typeof rec.confidence === 'number' ? rec.confidence : NaN)
  );
  const score = Number.isFinite(rawScore) ? Math.round(rawScore <= 1 ? rawScore * 100 : rawScore) : null;
  const resolved =
    rawTier === 'HIGH' || rawTier === 'MEDIUM' || rawTier === 'LOW'
      ? rawTier
      : score !== null
        ? score >= 80
          ? 'HIGH'
          : score >= 50
            ? 'MEDIUM'
            : 'LOW'
        : 'LOW';
  const sortScore = score ?? (resolved === 'HIGH' ? 85 : resolved === 'MEDIUM' ? 65 : 35);
  if (resolved === 'HIGH') {
    return {
      tier: 'HIGH',
      score,
      sortScore,
      badgeCls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/35',
    };
  }
  if (resolved === 'MEDIUM') {
    return {
      tier: 'MEDIUM',
      score,
      sortScore,
      badgeCls: 'bg-amber-500/15 text-amber-300 border-amber-500/35',
    };
  }
  return {
    tier: 'LOW',
    score,
    sortScore,
    badgeCls: 'bg-slate-800 text-slate-300 border-slate-700',
  };
};

export const buildWhyPickReasons = (rec, game) => {
  if (!rec) return [];
  const reasons = [];
  const home = game?.home_team || 'Home';
  const away = game?.away_team || 'Away';
  const sig = rec.signals || {};
  const betType = String(rec.bet_type || rec.market_type || '').toUpperCase();
  const sel = String(rec.selection || '');
  const edgePts = Number(rec.edge_points);

  if (Number.isFinite(edgePts) && Math.abs(edgePts) > 0) {
    const unit = betType === 'ML' ? '% win prob' : ' pts';
    reasons.push({
      label: 'Model vs Market',
      tone: 'indigo',
      text: `${sel || rec.pick} carries ${fmtSigned(edgePts, 1)}${unit} edge (Fair ${
        betType === 'ML' ? fmtPct(rec.fair_line ?? rec.calibrated_win_prob ?? rec.win_prob, 1) : rec.fair_line ?? '—'
      } vs Book ${betType === 'ML' ? fmtOdds(rec.price) : rec.market_line ?? '—'}).`,
    });
  }

  // Independent rating sources
  const pickedHome = sel.toLowerCase().includes(home.toLowerCase()) || String(rec.pick || '').toLowerCase() === home.toLowerCase();
  const teamLabel = pickedHome ? home : away;
  const sourceLines = [];
  const toSideFair = (homeSpread) => {
    const num = Number(homeSpread);
    if (!Number.isFinite(num)) return null;
    return pickedHome ? num : -num;
  };
  if (betType === 'SPREAD') {
    const tf = toSideFair(sig.torvik?.fair_spread_home);
    const hf = toSideFair(sig.haslametrics?.fair_spread_home);
    const kf = toSideFair(sig.kenpom?.fair_spread_home);
    if (tf !== null) sourceLines.push(`BartTorvik ${teamLabel} ${fmtSigned(tf, 1)}`);
    if (hf !== null) sourceLines.push(`Haslametrics ${teamLabel} ${fmtSigned(hf, 1)}`);
    if (kf !== null) sourceLines.push(`KenPom ${teamLabel} ${fmtSigned(kf, 1)}`);
  } else if (betType === 'TOTAL') {
    const tt = Number(sig.torvik?.fair_total);
    const ht = Number(sig.haslametrics?.fair_total);
    const kt = Number(sig.kenpom?.fair_total);
    if (Number.isFinite(tt)) sourceLines.push(`BartTorvik ${tt.toFixed(1)}`);
    if (Number.isFinite(ht)) sourceLines.push(`Haslametrics ${ht.toFixed(1)}`);
    if (Number.isFinite(kt)) sourceLines.push(`KenPom ${kt.toFixed(1)}`);
  }
  if (sourceLines.length > 0) {
    reasons.push({
      label: 'Independent Ratings',
      tone: 'blue',
      text: sourceLines.join(' • '),
    });
  }

  // Player-level injuries
  const injImp = sig.injuries_impact;
  if (injImp && (injImp.spread_adj || injImp.total_adj || (injImp.impact_players || []).length > 0)) {
    const names = (injImp.impact_players || [])
      .slice(0, 3)
      .map((p) => `${p.player} (${p.status}${p.est_pts ? `, ~${Number(p.est_pts).toFixed(1)} pts` : ''})`)
      .join(', ');
    reasons.push({
      label: 'Injury Impact Priced In',
      tone: 'amber',
      text: names
        ? `${names}. Adjusted line ${fmtSigned(injImp.spread_adj || 0, 1)} pts / total ${fmtSigned(injImp.total_adj || 0, 1)} pts.`
        : `Injury adjustment applied (${fmtSigned(injImp.spread_adj || 0, 1)} spread, ${fmtSigned(injImp.total_adj || 0, 1)} total).`,
    });
  } else if (Array.isArray(sig.injuries) && sig.injuries.length > 0) {
    reasons.push({
      label: 'Injury Watch',
      tone: 'amber',
      text: sig.injuries.slice(0, 2).map((i) => `${i.player} (${i.status})`).join(', '),
    });
  }

  // Splits & Line Movement
  const tags = Array.isArray(rec.movement_tags) ? rec.movement_tags : [];
  if (tags.includes('rlm_confirmed') || tags.includes('sharp_backing')) {
    reasons.push({
      label: tags.includes('rlm_confirmed') ? 'Sharp Money Line Move' : 'Big Money Backing',
      tone: 'emerald',
      text: tags.includes('rlm_confirmed')
        ? 'Public bettors lean the other way, while respected money pushed the line in favor of this pick.'
        : 'More total money than ticket count is backing this side.',
    });
  }

  // Extra narrative bullets
  if (Array.isArray(rec.key_factors) && rec.key_factors.length > 0 && reasons.length < 3) {
    reasons.push({
      label: 'Key Driver',
      tone: 'slate',
      text: String(rec.key_factors[0]),
    });
  }

  return reasons;
};

/**
 * Build a portable javascript: bookmarklet that extracts #ratings-table (with colspan headers)
 * from the user's own logged-in kenpom.com browser tab and opens Basement Bets with #kp_import=...
 */
export const buildKenpomBookmarklet = (appOrigin) => {
  const cleanOrigin = String(appOrigin || '').replace(/\/+$/, '');
  const destPrefix = JSON.stringify(`${cleanOrigin}/#kp_import=`);
  const body = `(function(){
    var t=document.querySelector('#ratings-table');
    if(!t){
      var ts=document.querySelectorAll('table');
      for(var k=0;k<ts.length;k++){
        var txt=(ts[k].innerText||'').slice(0,800);
        if(/NetRtg|AdjEM|ORtg|AdjOE/i.test(txt)){t=ts[k];break;}
      }
    }
    if(!t){
      if(confirm('You are not on kenpom.com yet.\\n\\nClick OK to open kenpom.com in a new tab. Once logged in with the rankings table on screen, click this bookmark again to sync back to Basement Bets.')){
        window.open('https://kenpom.com/','_blank');
      }
      return;
    }
    var hTr=[].slice.call(t.querySelectorAll('thead tr')).pop();
    var hdrs=[];
    if(hTr){
      [].slice.call(hTr.children).forEach(function(c){
        var lb=(c.innerText||c.textContent||'').replace(/\\s+/g,' ').trim();
        var sp=parseInt(c.getAttribute('colspan')||'1',10)||1;
        hdrs.push(lb);
        for(var j=1;j<sp;j++){hdrs.push(lb?lb+' Rank':'');}
      });
    }
    var lines=[];
    if(hdrs.length>=6){lines.push(hdrs.join('\\t'));}
    var tb=t.querySelector('tbody')||t;
    var trs=tb.querySelectorAll('tr');
    for(var r=0;r<trs.length;r++){
      if(trs[r].closest&&trs[r].closest('thead')){continue;}
      var cls=[].slice.call(trs[r].querySelectorAll('td,th')).map(function(c){
        return (c.innerText||c.textContent||'').replace(/\\s+/g,' ').trim();
      });
      if(cls.length>=6){lines.push(cls.join('\\t'));}
    }
    var tsv=lines.join('\\n');
    if(lines.length<10){
      alert('Found fewer than 10 rows. Make sure the full ratings table on kenpom.com is loaded.');
      return;
    }
    var bytes=new TextEncoder().encode(tsv);
    var bin='';
    for(var i=0;i<bytes.length;i+=8192){
      bin+=String.fromCharCode.apply(null,bytes.subarray(i,i+8192));
    }
    var b64=btoa(bin);
    var dest=${destPrefix}+encodeURIComponent(b64);
    try{if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(tsv).catch(function(){});}}catch(e){}
    var w=window.open(dest,'_blank');
    if(!w){
      window.location.href=dest;
    }
  })();`;
  return `javascript:${body.replace(/\n\s*/g, '')}`;
};

/**
 * Decode #kp_import=<base64> URL hash payload emitted by the KenPom bookmarklet into UTF-8 TSV text.
 */
export const decodeKenpomHashImport = (hashStr) => {
  const raw = String(hashStr || '');
  const idx = raw.indexOf('kp_import=');
  if (idx === -1) return null;
  let encoded = raw.slice(idx + 'kp_import='.length);
  const ampIdx = encoded.indexOf('&');
  if (ampIdx !== -1) encoded = encoded.slice(0, ampIdx);
  if (!encoded) return null;
  const b64 = decodeURIComponent(encoded);
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) {
    bytes[i] = bin.charCodeAt(i);
  }
  return new TextDecoder().decode(bytes);
};

const toNum = (v) => {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

const extractTeamAndLineFromSelection = (selection, fallbackTeam = '') => {
  const raw = String(selection || '').trim();
  const match = raw.match(/^(.*?)\s+([+-]?\d+(?:\.\d+)?)$/);
  if (match) {
    return { team: match[1].trim() || fallbackTeam, line: toNum(match[2]) };
  }
  return { team: raw || fallbackTeam, line: null };
};

/**
 * Derive a projected final score for both teams from model fair total and fair home spread.
 */
export const getProjectedScore = (game, analysis, rec) => {
  const home = game?.home_team || analysis?.matchup?.split(' @ ')?.[1] || 'Home';
  const away = game?.away_team || analysis?.matchup?.split(' @ ')?.[0] || 'Away';
  const ctx = analysis?.context || {};
  const sig = rec?.signals || analysis?.signals || analysis?.matchup_signals || {};

  let homeScore = toNum(ctx.projected_home_score ?? sig?.projected_score?.home);
  let awayScore = toNum(ctx.projected_away_score ?? sig?.projected_score?.away);

  if (homeScore == null || awayScore == null) {
    let fairTotal = toNum(ctx.fair_total ?? analysis?.fair_total ?? (String(rec?.bet_type || '').toUpperCase() === 'TOTAL' ? rec?.fair_line : null) ?? game?.total_line);
    let fairSpreadHome = toNum(ctx.fair_spread_home ?? analysis?.fair_spread_home);

    if (fairSpreadHome == null && String(rec?.bet_type || '').toUpperCase() === 'SPREAD' && toNum(rec?.fair_line) != null) {
      const selLow = String(rec?.selection || '').toLowerCase();
      const isHomePick = selLow.includes(home.toLowerCase());
      fairSpreadHome = isHomePick ? toNum(rec.fair_line) : -toNum(rec.fair_line);
    } else if (fairSpreadHome == null && toNum(game?.home_spread) != null) {
      fairSpreadHome = toNum(game.home_spread);
    }

    if (fairTotal != null && fairSpreadHome != null) {
      homeScore = Math.round((fairTotal - fairSpreadHome) / 2);
      awayScore = Math.round((fairTotal + fairSpreadHome) / 2);
    }
  }

  if (homeScore == null || awayScore == null) return null;

  const winner = homeScore >= awayScore ? home : away;
  const margin = Math.abs(homeScore - awayScore);
  return {
    homeTeam: home,
    awayTeam: away,
    homeScore,
    awayScore,
    winner,
    margin,
    text: `${away} ${awayScore} – ${home} ${homeScore}`,
    shortText: `${awayScore}–${homeScore}`,
    marginText:
      margin === 0
        ? `Projected toss-up (${awayScore}–${homeScore})`
        : `${winner} projected to win by ~${margin} ${margin === 1 ? 'pt' : 'pts'}`,
  };
};

/**
 * Translate spread (+37.5 / -4.5), total (OVER/UNDER), moneyline, odds (-110), and EV% into plain English.
 */
export const explainPickPlainly = (rec, game) => {
  if (!rec) return null;
  const betTypeRaw = String(rec.bet_type || rec.market || '').toUpperCase();
  const isTotal = betTypeRaw === 'TOTAL' || /\b(OVER|UNDER)\b/i.test(String(rec.selection || ''));
  const isMl = betTypeRaw === 'ML' || betTypeRaw === 'MONEYLINE';
  const betType = isTotal ? 'TOTAL' : isMl ? 'ML' : 'SPREAD';

  const parsed = extractTeamAndLineFromSelection(rec.selection || rec.pick, game?.home_team || 'Team');
  const line = toNum(rec.market_line ?? rec.line ?? parsed.line);
  const price = toNum(rec.price ?? rec.odds);
  const evDec = getRecEv(rec);

  let headline = String(rec.selection || rec.pick || 'Model Lean');
  let howItWins = '';
  let lineTranslation = '';
  let shortRule = '';

  if (betType === 'SPREAD' && line != null) {
    const absLine = Math.abs(line);
    const isWhole = Number.isInteger(absLine);
    const team = parsed.team;
    if (line > 0) {
      const loseUpTo = isWhole ? absLine - 1 : Math.floor(absLine);
      headline = `Bet on ${team} with a +${absLine}-point head start`;
      howItWins = isWhole
        ? `Wins if ${team} wins OR loses by ${loseUpTo} points or fewer (losing by exactly ${absLine} is a tie/refund).`
        : `Wins if ${team} wins OR loses by ${loseUpTo} points or fewer.`;
      lineTranslation = `+${absLine} means ${team} is the underdog getting ${absLine} bonus points added to their final score.`;
      shortRule = `Can lose by up to ${loseUpTo} pts`;
    } else if (line < 0) {
      const winBy = isWhole ? absLine + 1 : Math.floor(absLine) + 1;
      headline = `Bet on ${team} to win by ${winBy}+ points`;
      howItWins = isWhole
        ? `Wins if ${team} wins by ${winBy} or more points (winning by exactly ${absLine} is a tie/refund).`
        : `Wins if ${team} wins by ${winBy} or more points.`;
      lineTranslation = `${line} means ${team} is the favorite and must win by more than ${absLine} points.`;
      shortRule = `Must win by ${winBy}+ pts`;
    } else {
      headline = `Bet on ${team} to win (Pick'em)`;
      howItWins = `Wins if ${team} outscores their opponent (no point handicap).`;
      lineTranslation = `0 (Pick'em) means both teams start even — just pick the game winner.`;
      shortRule = `Must win outright`;
    }
  } else if (betType === 'TOTAL' && line != null) {
    const isOver = /OVER|^O\b/i.test(String(rec.selection || rec.side || ''));
    const isWhole = Number.isInteger(line);
    if (isOver) {
      const needPts = Math.floor(line) + 1;
      headline = `Combined Score OVER ${line} points`;
      howItWins = isWhole
        ? `Wins if both teams combine for ${needPts}+ total points (exactly ${line} is a tie/refund).`
        : `Wins if both teams combine for ${needPts}+ total points.`;
      lineTranslation = `Add both teams' final scores together — you want a higher-scoring game (${needPts}+ combined pts).`;
      shortRule = `Needs ${needPts}+ combined pts`;
    } else {
      const maxPts = isWhole ? line - 1 : Math.ceil(line) - 1;
      headline = `Combined Score UNDER ${line} points`;
      howItWins = isWhole
        ? `Wins if both teams combine for ${maxPts} or fewer total points (exactly ${line} is a tie/refund).`
        : `Wins if both teams combine for ${maxPts} or fewer total points.`;
      lineTranslation = `Add both teams' final scores together — you want a lower-scoring game (${maxPts} or fewer combined pts).`;
      shortRule = `Needs ${maxPts} or fewer total pts`;
    }
  } else if (betType === 'ML') {
    const team = parsed.team.replace(/\s*\b(ML|Moneyline)\b/i, '').trim();
    headline = `Bet on ${team} to win outright`;
    howItWins = `Wins if ${team} wins the game by any score (point spread does not matter).`;
    lineTranslation = `Moneyline = straight-up game winner with no point spread.`;
    shortRule = `Just needs to win`;
  }

  let oddsTranslation = '';
  if (price != null) {
    if (price < 0) {
      const profit = Math.round((100 / Math.abs(price)) * 100);
      oddsTranslation = `Odds ${price}: a $100 bet wins ~$${profit} profit (or bet $${Math.abs(price)} to win $100).`;
    } else if (price > 0) {
      oddsTranslation = `Odds +${price}: a $100 bet wins $${Math.round(price)} profit (underdog payout).`;
    }
  }

  let evTranslation = '';
  if (evDec != null) {
    const evPct = evDec * 100;
    const estProfit = evPct.toFixed(2);
    if (evPct >= 6) {
      evTranslation = `Strong Value (+${evPct.toFixed(1)}%): projected +$${estProfit} long-term profit per $100 staked.`;
    } else if (evPct >= 0) {
      evTranslation = `Positive Edge (+${evPct.toFixed(1)}%): projected +$${estProfit} long-term profit per $100 staked.`;
    } else {
      evTranslation = `Below Break-Even (${evPct.toFixed(1)}%): sportsbook price is too expensive vs our fair line.`;
    }
  }

  return {
    betType,
    headline,
    howItWins,
    lineTranslation,
    shortRule,
    oddsTranslation,
    evTranslation,
  };
};

/**
 * Build visual comparison bar data (Sportsbook vs Basement Fair Line + Torvik/Hasla/KenPom markers).
 */
export const buildVisualModelData = (rec, game, analysis) => {
  const betTypeRaw = String(rec?.bet_type || rec?.market || '').toUpperCase();
  const isTotal = betTypeRaw === 'TOTAL' || /\b(OVER|UNDER)\b/i.test(String(rec?.selection || ''));
  const home = game?.home_team || 'Home';
  const away = game?.away_team || 'Away';
  const sel = String(rec?.selection || '');
  const sig = rec?.signals || analysis?.signals || analysis?.matchup_signals || {};
  const ctx = analysis?.context || {};

  let mode = isTotal ? 'TOTAL' : 'SPREAD';
  let bookLine = toNum(rec?.market_line);
  let fairLine = toNum(rec?.fair_line);
  let sideLabel = '';
  let pickedHome = true;

  if (mode === 'TOTAL') {
    if (bookLine == null) bookLine = toNum(ctx.current_total ?? game?.total_line);
    if (fairLine == null) fairLine = toNum(ctx.fair_total ?? analysis?.fair_total);
    sideLabel = 'Combined Points';
  } else {
    pickedHome =
      sel.toLowerCase().includes(home.toLowerCase()) ||
      String(rec?.pick || '').toLowerCase() === home.toLowerCase() ||
      !sel;
    if (bookLine == null && toNum(game?.home_spread) != null) {
      bookLine = pickedHome ? toNum(game.home_spread) : -toNum(game.home_spread);
    }
    if (fairLine == null && toNum(ctx.fair_spread_home ?? analysis?.fair_spread_home) != null) {
      const hFair = toNum(ctx.fair_spread_home ?? analysis?.fair_spread_home);
      fairLine = pickedHome ? hFair : -hFair;
    }
    sideLabel = pickedHome ? `${home} Spread` : `${away} Spread`;
  }

  if (bookLine == null || fairLine == null || betTypeRaw === 'ML' || betTypeRaw === 'MONEYLINE') {
    return null;
  }

  const toSide = (homeVal) => {
    const n = toNum(homeVal);
    if (n == null) return null;
    return mode === 'TOTAL' ? n : pickedHome ? n : -n;
  };

  const sources = [];
  const tvLine = toSide(mode === 'TOTAL' ? sig.torvik?.fair_total : sig.torvik?.fair_spread_home);
  const hsLine = toSide(mode === 'TOTAL' ? sig.haslametrics?.fair_total : sig.haslametrics?.fair_spread_home);
  const kpLine = toSide(mode === 'TOTAL' ? sig.kenpom?.fair_total : sig.kenpom?.fair_spread_home);
  if (tvLine != null) sources.push({ id: 'torvik', label: 'BartTorvik', line: Number(tvLine.toFixed(1)), color: '#0ea5e9' });
  if (hsLine != null) sources.push({ id: 'hasla', label: 'Haslametrics', line: Number(hsLine.toFixed(1)), color: '#8b5cf6' });
  if (kpLine != null) sources.push({ id: 'kenpom', label: 'KenPom', line: Number(kpLine.toFixed(1)), color: '#10b981' });

  const allVals = [bookLine, fairLine, ...sources.map((s) => s.line)];
  const rawMin = Math.min(...allVals);
  const rawMax = Math.max(...allVals);
  const pad = Math.max(1.5, (rawMax - rawMin) * 0.25);
  const minVal = rawMin - pad;
  const maxVal = rawMax + pad;
  const span = Math.max(0.1, maxVal - minVal);
  const pct = (v) => Math.max(4, Math.min(96, ((v - minVal) / span) * 100));

  const diff = fairLine - bookLine;
  const cushionPts = Math.abs(diff);
  const fmtLine = (v) => (mode === 'TOTAL' ? Number(v).toFixed(1) : `${v > 0 ? '+' : ''}${Number(v).toFixed(1)}`);

  let summary = '';
  if (mode === 'TOTAL') {
    summary =
      diff >= 0
        ? `Sportsbook sets total at ${fmtLine(bookLine)} pts vs. Model projection of ${fmtLine(fairLine)} pts (+${cushionPts.toFixed(1)} pts higher).`
        : `Sportsbook sets total at ${fmtLine(bookLine)} pts vs. Model projection of ${fmtLine(fairLine)} pts (${cushionPts.toFixed(1)} pts lower).`;
  } else {
    const team = pickedHome ? home : away;
    summary =
      bookLine > fairLine
        ? `Sportsbook gives ${team} ${fmtLine(bookLine)} pts, while our model thinks ${team} only needs ${fmtLine(fairLine)} pts (${cushionPts.toFixed(1)} pts of extra safety cushion).`
        : `Sportsbook prices ${team} at ${fmtLine(bookLine)} pts vs. Model fair line of ${fmtLine(fairLine)} pts (${cushionPts.toFixed(1)} pts difference).`;
  }

  return {
    mode,
    sideLabel,
    bookLine: Number(bookLine.toFixed(1)),
    fairLine: Number(fairLine.toFixed(1)),
    bookLabel: fmtLine(bookLine),
    fairLabel: fmtLine(fairLine),
    bookPct: pct(bookLine),
    fairPct: pct(fairLine),
    cushionPts: Number(cushionPts.toFixed(1)),
    summary,
    sources: sources.map((s) => ({
      ...s,
      displayLine: fmtLine(s.line),
      pct: pct(s.line),
    })),
  };
};

/**
 * Determine live scoreboard status and live bet-tracking status against an active/final score.
 */
export const getLiveGameStatus = (game, rec) => {
  if (!game) return { state: 'UPCOMING', hasScore: false };
  const rawStatus = String(game.live_status || game.status || '').toUpperCase();
  const isFinal = Boolean(game.final) || rawStatus === 'FINAL' || rawStatus === 'COMPLETED';
  const isHalftime = !isFinal && rawStatus === 'HALFTIME';
  const isLive = !isFinal && (rawStatus === 'IN_PROGRESS' || rawStatus === 'LIVE' || isHalftime);

  const homeScore = toNum(game.home_score);
  const awayScore = toNum(game.away_score);
  const hasScore = homeScore != null && awayScore != null;

  let coverText = '';
  let coverTone = 'neutral';
  if (hasScore && rec) {
    const betType = String(rec.bet_type || rec.market || '').toUpperCase();
    const sel = String(rec.selection || '');
    const line = toNum(rec.market_line ?? extractTeamAndLineFromSelection(sel).line);
    const totalNow = homeScore + awayScore;

    if (betType === 'TOTAL' && line != null) {
      const isOver = /OVER|^O\b/i.test(sel);
      const diff = totalNow - line;
      if (isFinal) {
        if ((isOver && diff > 0) || (!isOver && diff < 0)) {
          coverText = `Bet Won (${totalNow} total pts)`;
          coverTone = 'win';
        } else if (diff === 0) {
          coverText = `Push (${totalNow} total pts)`;
        } else {
          coverText = `Bet Lost (${totalNow} total pts)`;
          coverTone = 'loss';
        }
      } else {
        coverText = `${totalNow} combined pts so far (${isOver ? `needs ${Math.max(0, Math.floor(line) + 1 - totalNow)} more` : `${Math.max(0, Math.ceil(line) - 1 - totalNow)} pts under cap`})`;
        coverTone = !isOver && totalNow < line ? 'win' : isOver && totalNow >= line ? 'win' : 'neutral';
      }
    } else if (line != null && (betType === 'SPREAD' || betType === '')) {
      const home = String(game.home_team || '').toLowerCase();
      const isHomePick = sel.toLowerCase().includes(home);
      const pickedScore = isHomePick ? homeScore : awayScore;
      const oppScore = isHomePick ? awayScore : homeScore;
      const marginWithLine = pickedScore + line - oppScore;
      const absDiff = Math.abs(marginWithLine).toFixed(1).replace(/\.0$/, '');
      if (marginWithLine > 0) {
        coverText = isFinal ? `Covered by +${absDiff} pts` : `Covering by +${absDiff} pts`;
        coverTone = 'win';
      } else if (marginWithLine === 0) {
        coverText = isFinal ? 'Push (tie against spread)' : 'Even against spread';
      } else {
        coverText = isFinal ? `Missed spread by ${absDiff} pts` : `Trailing spread by ${absDiff} pts`;
        coverTone = 'loss';
      }
    }
  }

  return {
    state: isFinal ? 'FINAL' : isLive ? 'LIVE' : 'UPCOMING',
    isFinal,
    isLive,
    isHalftime,
    hasScore,
    homeScore,
    awayScore,
    statusDetail: game.status_detail || (isFinal ? 'Final' : isHalftime ? 'Halftime' : isLive ? 'Live' : ''),
    coverText,
    coverTone,
  };
};

/**
 * Extract structured backend model weights, consensus counts, situational adjustments,
 * blowout variance guard, and open-to-current line movement from rec / context / debug.
 */
export const getModelSignalData = (rec, context, debugInfo, game) => {
  const sig = rec?.signals || {};
  const ctx = context || {};
  const dbg = debugInfo || {};
  const adj = sig.adjustments || dbg.adjustments || {};
  const w = sig.weights || {};

  const betType = String(rec?.bet_type || rec?.market || '').toUpperCase();
  const isTotalBet =
    betType === 'TOTAL' || /\b(OVER|UNDER)\b/i.test(String(rec?.selection || ''));

  const wTorvik = toNum(w.torvik ?? ctx.w_base ?? dbg.w_base) ?? 0;
  const wHasla = toNum(w.haslametrics ?? ctx.w_hasla ?? dbg.w_hasla) ?? 0;
  const wKenpom = toNum(w.kenpom ?? ctx.w_kp ?? dbg.w_kp) ?? 0;
  const effWeight =
    toNum(adj.efficiency_weight ?? ctx.efficiency_weight) ??
    wTorvik + wHasla + wKenpom;

  const modelPct = effWeight > 0 ? Math.min(80, Math.round(effWeight * 100)) : null;
  const marketPct = modelPct != null ? Math.max(0, 100 - modelPct) : null;

  const convSpread = Number(
    adj.conviction_sources ?? ctx.conviction_sources ?? dbg.conviction_sources ?? 0
  );
  const convTotal = Number(
    adj.conviction_sources_total ??
      ctx.conviction_sources_total ??
      dbg.conviction_sources_total ??
      0
  );
  const convCount = isTotalBet ? (convTotal || convSpread) : (convSpread || convTotal);

  const activeSourceCount =
    [
      sig.torvik || wTorvik > 0,
      sig.haslametrics || wHasla > 0,
      sig.kenpom || wKenpom > 0,
    ].filter(Boolean).length || (effWeight > 0 ? 1 : 0);

  // Convert home-spread coordinates into plain-English favored-team shifts
  const homeName = game?.home_team || 'Home';
  const awayName = game?.away_team || 'Away';
  const describeSpreadShift = (homeSpreadDelta) => {
    const val = toNum(homeSpreadDelta);
    if (val == null || Math.abs(val) < 0.05) return null;
    // Negative delta makes home spread more negative => favors Home
    const favorsHome = val < 0;
    return {
      deltaHome: Number(val.toFixed(2)),
      pts: Number(Math.abs(val).toFixed(1)),
      favors: favorsHome ? homeName : awayName,
      text: `${favorsHome ? homeName : awayName} +${Math.abs(val).toFixed(1)} pt`,
    };
  };

  const sosVal = toNum(adj.sos_adj ?? ctx.sos_adj ?? dbg.sos_adj) ?? 0;
  const momVal = toNum(adj.mom_adj ?? ctx.mom_adj ?? dbg.mom_adj) ?? 0;
  const fatigueVal = toNum(adj.fatigue_adj ?? ctx.fatigue_adj ?? dbg.fatigue_adj) ?? 0;
  const spotVal = toNum(adj.spot_adj ?? ctx.spot_adj ?? dbg.spot_adj) ?? 0;
  const shootVal = toNum(adj.shooting_adj ?? ctx.shooting_adj ?? dbg.shooting_adj) ?? 0;
  const injSpreadVal =
    toNum(adj.injury_spread_adj ?? ctx.injury_spread_adj ?? dbg.injury_spread_adj) ?? 0;
  const injTotalVal =
    toNum(adj.injury_total_adj ?? ctx.injury_total_adj ?? dbg.injury_total_adj) ?? 0;
  const blowoutSigmaAdd = toNum(adj.blowout_sigma_add ?? ctx.blowout_sigma_add) ?? 0;

  // In model: mu_spread_final -= (sos_adj + mom_adj); others are added directly
  const sosMomShift = describeSpreadShift(-(sosVal + momVal));
  const restSpotShift = describeSpreadShift(fatigueVal + spotVal);
  const shootingShift = describeSpreadShift(shootVal);
  const injurySpreadShift = describeSpreadShift(injSpreadVal);

  const openSpreadHome = toNum(ctx.open_spread_home);
  const currentSpreadHome = toNum(ctx.current_spread_home ?? game?.home_spread);
  const spreadMove =
    openSpreadHome != null &&
    currentSpreadHome != null &&
    Math.abs(currentSpreadHome - openSpreadHome) >= 0.5
      ? {
          open: openSpreadHome,
          current: currentSpreadHome,
          text: `${fmtSigned(openSpreadHome, 1)} → ${fmtSigned(currentSpreadHome, 1)}`,
        }
      : null;

  const openTotal = toNum(ctx.open_total);
  const currentTotal = toNum(ctx.current_total ?? game?.total_line);
  const totalMove =
    openTotal != null &&
    currentTotal != null &&
    Math.abs(currentTotal - openTotal) >= 0.5
      ? {
          open: openTotal,
          current: currentTotal,
          text: `${openTotal.toFixed(1)} → ${currentTotal.toFixed(1)}`,
        }
      : null;

  const pills = [];
  if (convCount >= 2 && modelPct != null) {
    pills.push({
      id: 'consensus',
      tone: 'indigo',
      label: `${convCount}/${Math.max(convCount, activeSourceCount)} Ratings Agree · ${modelPct}% Model Wt`,
    });
  } else if (modelPct != null && modelPct > 0) {
    pills.push({
      id: 'weight',
      tone: 'blue',
      label: `${modelPct}% Model / ${marketPct}% Book Wt`,
    });
  }

  if (sosMomShift && sosMomShift.pts >= 0.1) {
    pills.push({
      id: 'sos-mom',
      tone: 'emerald',
      label: `SOS/Form: ${sosMomShift.text}`,
    });
  }
  if (restSpotShift && restSpotShift.pts >= 0.1) {
    pills.push({
      id: 'rest-spot',
      tone: 'amber',
      label: `Rest/Spot: ${restSpotShift.text}`,
    });
  }
  if (shootingShift && shootingShift.pts >= 0.1) {
    pills.push({
      id: 'shooting',
      tone: 'slate',
      label: `3PT Regress: ${shootingShift.text}`,
    });
  }
  if (blowoutSigmaAdd >= 0.1) {
    pills.push({
      id: 'blowout',
      tone: 'amber',
      label: `Blowout Guard +${blowoutSigmaAdd.toFixed(1)}σ`,
    });
  }
  if (isTotalBet && totalMove) {
    pills.push({
      id: 'total-move',
      tone: 'blue',
      label: `Line Move: ${totalMove.text}`,
    });
  } else if (!isTotalBet && spreadMove) {
    pills.push({
      id: 'spread-move',
      tone: 'blue',
      label: `Line Move: ${spreadMove.text}`,
    });
  }

  return {
    modelPct,
    marketPct,
    convCount,
    activeSourceCount,
    weights: {
      torvik: wTorvik,
      haslametrics: wHasla,
      kenpom: wKenpom,
    },
    sosMomShift,
    restSpotShift,
    shootingShift,
    injurySpreadShift,
    injTotalVal: Math.abs(injTotalVal) >= 0.1 ? Number(injTotalVal.toFixed(1)) : null,
    blowoutSigmaAdd: blowoutSigmaAdd >= 0.1 ? Number(blowoutSigmaAdd.toFixed(1)) : null,
    spreadMove,
    totalMove,
    pills,
  };
};
