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
  if (t === 'rlm_confirmed') return { label: 'Pro Money Line Move', tone: 'emerald' };
  if (t === 'sharp_backing') return { label: 'Big Money Backing', tone: 'emerald' };
  if (t === 'injury_line_adjusted') return { label: 'Injury Priced In', tone: 'amber' };
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
 * Build a 1-click Chrome bookmarklet (`javascript:...`) that runs on kenpom.com,
 * fetches all 7 KenPom pages in parallel using the browser's active session cookies,
 * bundles them into a JSON payload, and passes them back to Basement Bets via #kp_import=.
 */
export const buildKenpomBookmarklet = (appOrigin) => {
  const cleanOrigin = String(appOrigin || '').replace(/\/+$/, '');
  const destPrefix = JSON.stringify(`${cleanOrigin}/#kp_import=`);
  const body = `(function(){
    if(location.hostname.indexOf('kenpom.com')===-1){
      if(confirm('You are not on kenpom.com yet.\\n\\nClick OK to open kenpom.com in a new tab. Once logged in, click this bookmark again to sync all 7 KenPom datasets back to Basement Bets.')){
        window.open('https://kenpom.com/','_blank');
      }
      return;
    }
    var old=document.getElementById('bb-kp-sync');
    if(old&&old.parentNode){old.parentNode.removeChild(old);}
    var pill=document.createElement('div');
    pill.id='bb-kp-sync';
    pill.style.cssText='position:fixed;top:16px;right:16px;z-index:2147483647;background:#0f172a;color:#6ee7b7;border:1px solid #10b981;padding:12px 16px;border-radius:10px;font:600 13px/1.4 system-ui,sans-serif;box-shadow:0 10px 25px rgba(0,0,0,0.45);';
    pill.textContent='Basement Bets: Syncing all 7 KenPom pages (Ratings, Four Factors, Height/Exp, HCA, Players, Refs, FanMatch)...';
    if(document.body){document.body.appendChild(pill);}
    function grabTsv(doc,maxRows){
      if(!doc){return '';}
      var t=doc.querySelector('#ratings-table');
      if(!t){
        var ts=doc.querySelectorAll('table');
        var bestLen=0;
        for(var k=0;k<ts.length;k++){
          var txt=(ts[k].innerText||ts[k].textContent||'').slice(0,800);
          var nTr=ts[k].querySelectorAll('tr').length;
          if(/NetRtg|AdjEM|ORtg|AdjOE|eFG%|Continuity|HCA|Official|Ref|Prediction|Player/i.test(txt)&&nTr>bestLen){
            t=ts[k];bestLen=nTr;
          }
        }
        if(!t&&ts.length){t=ts[0];}
      }
      if(!t){return '';}
      var hTrs=t.querySelectorAll('thead tr');
      var hTr=hTrs.length?hTrs[hTrs.length-1]:null;
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
      if(hdrs.length>=2){lines.push(hdrs.join('\\t'));}
      var tb=t.querySelector('tbody')||t;
      var trs=tb.querySelectorAll('tr');
      var limit=maxRows?Math.min(trs.length,maxRows):trs.length;
      for(var r=0;r<limit;r++){
        if(trs[r].closest&&trs[r].closest('thead')){continue;}
        var cls=[].slice.call(trs[r].querySelectorAll('td,th')).map(function(c){
          return (c.innerText||c.textContent||'').replace(/\\s+/g,' ').trim();
        });
        if(cls.length>=2){lines.push(cls.join('\\t'));}
      }
      return lines.join('\\n');
    }
    function fetchPage(url,maxRows){
      return fetch(url,{credentials:'include'}).then(function(resp){
        if(!resp.ok){return '';}
        return resp.text();
      }).then(function(html){
        if(!html){return '';}
        var doc=new DOMParser().parseFromString(html,'text/html');
        return grabTsv(doc,maxRows);
      }).catch(function(){return '';});
    }
    var ratingsP=document.querySelector('#ratings-table')?Promise.resolve(grabTsv(document)):fetchPage('/');
    Promise.all([
      ratingsP,
      fetchPage('/stats.php'),
      fetchPage('/height.php'),
      fetchPage('/hca.php'),
      fetchPage('/playerstats.php?s=ORtg',1200),
      fetchPage('/officials.php'),
      fetchPage('/fanmatch.php')
    ]).then(function(res){
      if(pill.parentNode){pill.parentNode.removeChild(pill);}
      if(!res[0]||res[0].split('\\n').length<10){
        alert('Could not find the full KenPom ratings table. Make sure you are logged in to kenpom.com, then click this bookmark again.');
        return;
      }
      var payload=JSON.stringify({
        _kp_bundle:1,
        ratings:res[0],
        stats:res[1],
        height:res[2],
        hca:res[3],
        playerstats:res[4],
        refs:res[5],
        fanmatch:res[6]
      });
      if(payload.length>900000&&res[4]){
        payload=JSON.stringify({
          _kp_bundle:1,
          ratings:res[0],
          stats:res[1],
          height:res[2],
          hca:res[3],
          playerstats:res[4].split('\\n').slice(0,601).join('\\n'),
          refs:res[5],
          fanmatch:res[6]
        });
      }
      try{if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(payload).catch(function(){});}}catch(e){}
      var bytes=new TextEncoder().encode(payload);
      var bin='';
      for(var i=0;i<bytes.length;i+=8192){
        bin+=String.fromCharCode.apply(null,bytes.subarray(i,i+8192));
      }
      var b64=btoa(bin);
      var dest=${destPrefix}+encodeURIComponent(b64);
      var w=window.open(dest,'_blank');
      if(!w){window.location.href=dest;}
    }).catch(function(err){
      if(pill.parentNode){pill.parentNode.removeChild(pill);}
      alert('KenPom sync error: '+(err&&err.message?err.message:err));
    });
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

const clamp = (val, min, max) => Math.max(min, Math.min(max, val));

/**
 * Standard normal CDF via Abramowitz-Stegun erf approximation.
 */
export const normalCdf = (z) => {
  const x = Number(z);
  if (!Number.isFinite(x)) return 0.5;
  const sign = x < 0 ? -1 : 1;
  const absX = Math.abs(x) / Math.SQRT2;
  const t = 1 / (1 + 0.3275911 * absX);
  const y =
    1 -
    (((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) *
      t) *
      Math.exp(-absX * absX);
  return clamp(0.5 * (1 + sign * y), 0.001, 0.999);
};

/**
 * Parse basketball/football clock strings like "11:42", "0:48.5", or "34.2" into decimal minutes.
 */
export const parseClockMinutes = (clockStr) => {
  if (clockStr === null || clockStr === undefined || clockStr === '') return null;
  const s = String(clockStr).trim();
  if (!s) return null;
  const mmss = s.match(/^(\d{1,2}):(\d{1,2}(?:\.\d+)?)$/);
  if (mmss) {
    const mins = parseInt(mmss[1], 10);
    const secs = parseFloat(mmss[2]);
    if (Number.isFinite(mins) && Number.isFinite(secs)) {
      return mins + secs / 60;
    }
  }
  const secsOnly = s.match(/^(\d+(?:\.\d+)?)$/);
  if (secsOnly) {
    const secs = parseFloat(secsOnly[1]);
    if (Number.isFinite(secs)) return secs / 60;
  }
  return null;
};

const resolveLiveFlags = (game) => {
  const rawStatus = String(game?.live_status || game?.status || '').toUpperCase();
  const statusDetail = String(game?.status_detail || '').trim();
  const isFinal = Boolean(game?.final) || rawStatus === 'FINAL' || rawStatus === 'COMPLETED';
  const isHalftime =
    !isFinal &&
    (rawStatus === 'HALFTIME' ||
      /\bHALFTIME\b/i.test(statusDetail) ||
      /^HALF$/i.test(statusDetail));
  const isLive =
    !isFinal && (rawStatus === 'IN_PROGRESS' || rawStatus === 'LIVE' || isHalftime);
  return { rawStatus, statusDetail, isFinal, isHalftime, isLive };
};

/**
 * Estimate live elapsed/remaining minutes and % played across NCAAM, NFL, and EPL.
 */
export const estimateLiveGameProgress = (game, pregameTotal = 142) => {
  const sport = String(game?.sport || 'NCAAM').toUpperCase();
  const isSoccer = sport === 'EPL' || sport === 'SOCCER';
  const isNfl = sport === 'NFL' || sport === 'NCAAF';
  const isNba = sport === 'NBA';
  const regPeriods = isNfl || isNba ? 4 : 2;
  const periodMins = isNfl ? 15 : isNba ? 12 : isSoccer ? 45 : 20;
  const otMins = isNfl ? 10 : isSoccer ? 15 : 5;
  const regTotalMins = regPeriods * periodMins;

  const { statusDetail, isFinal, isHalftime, isLive } = resolveLiveFlags(game);

  if (isFinal) {
    return {
      elapsedMinutes: regTotalMins,
      remainingMinutes: 0,
      totalGameMinutes: regTotalMins,
      elapsedFraction: 1,
      progressPct: 100,
      periodLabel: 'Final',
    };
  }

  if (!isLive) {
    return {
      elapsedMinutes: 0,
      remainingMinutes: regTotalMins,
      totalGameMinutes: regTotalMins,
      elapsedFraction: 0,
      progressPct: 0,
      periodLabel: statusDetail || 'Upcoming',
    };
  }

  if (isHalftime) {
    return {
      elapsedMinutes: regTotalMins / 2,
      remainingMinutes: regTotalMins / 2,
      totalGameMinutes: regTotalMins,
      elapsedFraction: 0.5,
      progressPct: 50,
      periodLabel: 'Halftime',
    };
  }

  let period = toNum(game?.period);
  let clockStr = game?.clock ? String(game.clock).trim() : '';

  if (!clockStr && statusDetail) {
    const cm = statusDetail.match(/\b(\d{1,2}:\d{2}(?:\.\d+)?)\b/);
    if (cm) clockStr = cm[1];
  }

  if (period == null && statusDetail) {
    const otMatch = statusDetail.match(/\b(\d*)\s*OT\b/i);
    if (otMatch) {
      const otNum = otMatch[1] ? parseInt(otMatch[1], 10) : 1;
      period = regPeriods + (Number.isFinite(otNum) && otNum > 0 ? otNum : 1);
    } else if (/\b(?:1st|1H|Q1)\b/i.test(statusDetail)) {
      period = 1;
    } else if (/\b(?:2nd|2H|Q2)\b/i.test(statusDetail)) {
      period = 2;
    } else if (/\b(?:3rd|3H|Q3)\b/i.test(statusDetail)) {
      period = 3;
    } else if (/\b(?:4th|4H|Q4)\b/i.test(statusDetail)) {
      period = 4;
    }
  }

  const formatOrdinalPeriod = (p) => {
    if (p > regPeriods) {
      const otIdx = p - regPeriods;
      return otIdx === 1 ? 'OT' : `${otIdx}OT`;
    }
    if (p === 1) return isNfl || isNba ? 'Q1' : '1st';
    if (p === 2) return isNfl || isNba ? 'Q2' : '2nd';
    if (p === 3) return 'Q3';
    if (p === 4) return 'Q4';
    return `${p}`;
  };

  if (isSoccer && statusDetail) {
    const socMinMatch = statusDetail.match(/(\d+)(?:\+(\d+))?\s*'/);
    if (socMinMatch) {
      const baseM = parseInt(socMinMatch[1], 10);
      const stopM = socMinMatch[2] ? parseInt(socMinMatch[2], 10) : 0;
      const elapsedMinutes = clamp(baseM + stopM * 0.25, 1, 120);
      const totalGameMinutes = elapsedMinutes > 90 ? 120 : 90;
      const remainingMinutes = Math.max(0, totalGameMinutes - elapsedMinutes);
      const elapsedFraction = clamp(elapsedMinutes / totalGameMinutes, 0.04, 0.98);
      return {
        elapsedMinutes: Number(elapsedMinutes.toFixed(1)),
        remainingMinutes: Number(remainingMinutes.toFixed(1)),
        totalGameMinutes,
        elapsedFraction,
        progressPct: Math.round(elapsedFraction * 100),
        periodLabel: statusDetail,
      };
    }
  }

  const clockRemMins = parseClockMinutes(clockStr);
  if (period != null && period >= 1) {
    let totalGameMinutes = regTotalMins;
    let elapsedMinutes;
    let remainingMinutes;
    if (period <= regPeriods) {
      const remInPeriod = clockRemMins != null ? clamp(clockRemMins, 0, periodMins) : periodMins * 0.5;
      elapsedMinutes = (period - 1) * periodMins + (periodMins - remInPeriod);
      remainingMinutes = (regPeriods - period) * periodMins + remInPeriod;
    } else {
      const otIndex = period - regPeriods;
      totalGameMinutes = regTotalMins + otIndex * otMins;
      const remInOt = clockRemMins != null ? clamp(clockRemMins, 0, otMins) : otMins * 0.5;
      elapsedMinutes = regTotalMins + (otIndex - 1) * otMins + (otMins - remInOt);
      remainingMinutes = remInOt;
    }
    const elapsedFraction = clamp(elapsedMinutes / Math.max(1, totalGameMinutes), 0.04, 0.98);
    const baseLabel = formatOrdinalPeriod(period);
    const periodLabel = clockStr ? `${baseLabel} · ${clockStr}` : baseLabel;
    return {
      elapsedMinutes: Number(elapsedMinutes.toFixed(2)),
      remainingMinutes: Number(Math.max(0, remainingMinutes).toFixed(2)),
      totalGameMinutes,
      elapsedFraction,
      progressPct: Math.round(elapsedFraction * 100),
      periodLabel,
    };
  }

  // Fallback when period/clock metadata are absent on an active live game
  const homeScore = toNum(game?.home_score);
  const awayScore = toNum(game?.away_score);
  const scoreFrac =
    homeScore != null && awayScore != null && pregameTotal > 10
      ? (homeScore + awayScore) / pregameTotal
      : null;
  let wallFrac = null;
  if (game?.start_time) {
    const startMs = new Date(game.start_time).getTime();
    if (Number.isFinite(startMs)) {
      const realMins = Math.max(0, (Date.now() - startMs) / 60000);
      wallFrac = realMins / (isSoccer ? 110 : isNfl ? 185 : 120);
    }
  }
  const fallbackFrac = clamp(
    scoreFrac != null && wallFrac != null
      ? scoreFrac * 0.65 + wallFrac * 0.35
      : scoreFrac ?? wallFrac ?? 0.35,
    0.04,
    0.95
  );
  const elapsedMinutes = fallbackFrac * regTotalMins;
  const remainingMinutes = regTotalMins - elapsedMinutes;
  return {
    elapsedMinutes: Number(elapsedMinutes.toFixed(1)),
    remainingMinutes: Number(remainingMinutes.toFixed(1)),
    totalGameMinutes: regTotalMins,
    elapsedFraction: fallbackFrac,
    progressPct: Math.round(fallbackFrac * 100),
    periodLabel: statusDetail || 'Live',
  };
};

const isHomeSelectionForGame = (selection, rec, game) => {
  const sideRaw = String(rec?.side || '').trim().toUpperCase();
  if (sideRaw === 'HOME') return true;
  if (sideRaw === 'AWAY') return false;

  const clean = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  const parsed = extractTeamAndLineFromSelection(selection);
  const pickNorm = clean(parsed.team.replace(/\s*\b(ml|moneyline)\b/gi, ''));
  const homeRaw = String(game?.home_team || '');
  const awayRaw = String(game?.away_team || '');
  const homeNorm = clean(homeRaw);
  const awayNorm = clean(awayRaw);

  if (homeNorm && pickNorm === homeNorm) return true;
  if (awayNorm && pickNorm === awayNorm) return false;

  const selNorm = clean(selection);
  const matchesHome = Boolean(homeNorm && (pickNorm.includes(homeNorm) || selNorm.includes(homeNorm)));
  const matchesAway = Boolean(awayNorm && (pickNorm.includes(awayNorm) || selNorm.includes(awayNorm)));
  if (matchesHome && !matchesAway) return true;
  if (matchesAway && !matchesHome) return false;
  if (matchesHome && matchesAway) {
    return homeNorm.length >= awayNorm.length;
  }
  return String(selection || '').toLowerCase().includes(homeRaw.toLowerCase());
};

/**
 * Determine live scoreboard status, live scoring pace, projected final score,
 * and whether a bet is trending to win or lose against the clock.
 */
export const getLiveGameStatus = (game, rec = null, context = null) => {
  if (!game) return { state: 'UPCOMING', hasScore: false };
  const { isFinal, isHalftime, isLive } = resolveLiveFlags(game);

  const homeScore = toNum(game.home_score);
  const awayScore = toNum(game.away_score);
  const hasScore = homeScore != null && awayScore != null;

  const betTypeRaw = String(rec?.bet_type || rec?.market || rec?.market_type || '').toUpperCase();
  const sel = String(rec?.selection || rec?.pick || '');
  const isTotalBet = betTypeRaw === 'TOTAL' || /\b(OVER|UNDER)\b/i.test(sel);
  const isMlBet = betTypeRaw === 'ML' || betTypeRaw === 'MONEYLINE' || /\b(ML|MONEYLINE)\b/i.test(sel);
  const betType = isTotalBet ? 'TOTAL' : isMlBet ? 'ML' : betTypeRaw || 'SPREAD';

  const pregameTotal =
    toNum(
      context?.fair_total ??
        (isTotalBet ? rec?.fair_line : null) ??
        rec?.market_line ??
        game?.total_line ??
        game?.total
    ) ?? 142;

  const isHomePickForSpread = rec ? isHomeSelectionForGame(sel, rec, game) : true;
  const fallbackSpreadHome =
    rec && !isTotalBet && !isMlBet && toNum(rec?.market_line ?? extractTeamAndLineFromSelection(sel).line) != null
      ? (isHomePickForSpread
          ? toNum(rec?.market_line ?? extractTeamAndLineFromSelection(sel).line)
          : -toNum(rec?.market_line ?? extractTeamAndLineFromSelection(sel).line))
      : 0;
  const pregameHomeSpread =
    toNum(context?.fair_spread_home ?? game?.home_spread ?? game?.spread_home) ?? fallbackSpreadHome;
  const pregameHomeMargin = -pregameHomeSpread;

  const progress = estimateLiveGameProgress(game, pregameTotal);

  let totalNow = null;
  let pointsPerMinute = null;
  let liveProjTotal = null;
  let liveProjHomeMargin = null;
  let liveProjHomeScore = null;
  let liveProjAwayScore = null;
  let gameTrendText = '';

  if (hasScore) {
    totalNow = homeScore + awayScore;
    if (isFinal) {
      pointsPerMinute =
        progress.elapsedMinutes > 0 ? Number((totalNow / progress.elapsedMinutes).toFixed(2)) : null;
      liveProjTotal = totalNow;
      liveProjHomeMargin = homeScore - awayScore;
      liveProjHomeScore = homeScore;
      liveProjAwayScore = awayScore;
      gameTrendText = `Final: ${game.away_team || 'Away'} ${awayScore} – ${game.home_team || 'Home'} ${homeScore} (${totalNow} pts)`;
    } else if (isLive) {
      const elapsedFrac = progress.elapsedFraction;
      const remFrac = Math.max(0, 1 - elapsedFrac);
      const liveWeight = clamp(elapsedFrac * 0.85, 0.15, 0.8);
      pointsPerMinute =
        progress.elapsedMinutes > 0.5 ? Number((totalNow / progress.elapsedMinutes).toFixed(2)) : null;

      const rawPaceTotal = clamp(totalNow / Math.max(0.04, elapsedFrac), 75, 235);
      const blendedTotalRate = liveWeight * rawPaceTotal + (1 - liveWeight) * pregameTotal;
      liveProjTotal = Number(Math.max(totalNow, totalNow + blendedTotalRate * remFrac).toFixed(1));

      const currentHomeMargin = homeScore - awayScore;
      const rawPaceHomeMargin = clamp(currentHomeMargin / Math.max(0.04, elapsedFrac), -35, 35);
      const blendedMarginRate = liveWeight * rawPaceHomeMargin + (1 - liveWeight) * pregameHomeMargin;
      liveProjHomeMargin = Number((currentHomeMargin + blendedMarginRate * remFrac).toFixed(1));

      const remTotal = Math.max(0, liveProjTotal - totalNow);
      const remMargin = liveProjHomeMargin - currentHomeMargin;
      let remHome = (remTotal + remMargin) / 2;
      let remAway = (remTotal - remMargin) / 2;
      if (remHome < 0) {
        remHome = 0;
        remAway = remTotal;
      } else if (remAway < 0) {
        remAway = 0;
        remHome = remTotal;
      }
      liveProjHomeScore = Math.max(homeScore, Math.round(homeScore + remHome));
      liveProjAwayScore = Math.max(awayScore, Math.round(awayScore + remAway));
      gameTrendText = `Live Pace: ${game.away_team || 'Away'} ${liveProjAwayScore} – ${game.home_team || 'Home'} ${liveProjHomeScore} (~${Math.round(liveProjTotal)} pts)`;
    }
  }

  let coverText = '';
  let coverTone = 'neutral';
  let trendVerdict = null;
  let trendLabel = '';
  let liveWinProb = null;
  let trendDetail = '';
  let projectedBetMargin = null;

  if (hasScore && rec && (isLive || isFinal)) {
    const parsedSel = extractTeamAndLineFromSelection(sel);
    const line = toNum(rec.market_line ?? rec.line ?? parsedSel.line);
    const remFrac = Math.max(0.03, 1 - progress.elapsedFraction);
    const remMinsLabel = `${Math.max(0, Math.round(progress.remainingMinutes))} min`;

    if (betType === 'TOTAL' && line != null) {
      const isOver = /OVER|^O\b/i.test(sel || String(rec.side || ''));
      const lineStr = Number(line).toFixed(1).replace(/\.0$/, '');
      const sideTag = isOver ? `O ${lineStr}` : `U ${lineStr}`;

      if (isFinal) {
        const diff = totalNow - line;
        projectedBetMargin = Number((isOver ? diff : -diff).toFixed(1));
        if ((isOver && diff > 0) || (!isOver && diff < 0)) {
          trendVerdict = 'WON';
          trendLabel = 'Won';
          liveWinProb = 1;
          coverText = `Bet Won (${totalNow} total pts vs ${sideTag})`;
          coverTone = 'win';
          trendDetail = `Final total finished at ${totalNow} pts, clearing ${sideTag} by ${Math.abs(diff).toFixed(1)} pts.`;
        } else if (diff === 0) {
          trendVerdict = 'PUSH';
          trendLabel = 'Push';
          liveWinProb = 0.5;
          coverText = `Push (${totalNow} total pts)`;
          trendDetail = `Final total landed on ${totalNow} pts (exact push/refund).`;
        } else {
          trendVerdict = 'LOST';
          trendLabel = 'Lost';
          liveWinProb = 0;
          coverText = `Bet Lost (${totalNow} total pts vs ${sideTag})`;
          coverTone = 'loss';
          trendDetail = `Final total finished at ${totalNow} pts, missing ${sideTag} by ${Math.abs(diff).toFixed(1)} pts.`;
        }
      } else if (isLive) {
        if (isOver && totalNow > line) {
          trendVerdict = 'TRENDING_WIN';
          trendLabel = 'Trending to Win';
          liveWinProb = 0.99;
          projectedBetMargin = Number((liveProjTotal - line).toFixed(1));
          coverTone = 'win';
          coverText = `Already Cashed (99%) · ${totalNow} > ${lineStr}`;
          trendDetail = `Already over ${lineStr} with ${totalNow} combined pts and ${remMinsLabel} left — bet is locked in.`;
        } else if (!isOver && totalNow > line) {
          trendVerdict = 'TRENDING_LOSE';
          trendLabel = 'Trending to Lose';
          liveWinProb = 0.01;
          projectedBetMargin = Number((line - totalNow).toFixed(1));
          coverTone = 'loss';
          coverText = `Over Limit (1%) · ${totalNow} > ${lineStr}`;
          trendDetail = `Combined score (${totalNow} pts) already exceeded Under ${lineStr}.`;
        } else {
          const projectedEdgeVsLine = Number((isOver ? liveProjTotal - line : line - liveProjTotal).toFixed(1));
          projectedBetMargin = projectedEdgeVsLine;
          const sigmaTotalRem = Math.max(2.0, 13.5 * Math.sqrt(remFrac));
          liveWinProb = Number(clamp(normalCdf(projectedEdgeVsLine / sigmaTotalRem), 0.02, 0.98).toFixed(2));

          if (projectedEdgeVsLine >= 1.5) {
            trendVerdict = 'TRENDING_WIN';
            trendLabel = 'Trending to Win';
            coverTone = 'win';
          } else if (projectedEdgeVsLine <= -1.5) {
            trendVerdict = 'TRENDING_LOSE';
            trendLabel = 'Trending to Lose';
            coverTone = 'loss';
          } else {
            trendVerdict = 'TOSS_UP';
            trendLabel = 'Tight / Toss-Up';
            coverTone = 'tossup';
          }

          const pctTxt = `${Math.round(liveWinProb * 100)}%`;
          coverText = `${trendLabel} (${pctTxt}) · Pace ${liveProjTotal.toFixed(1)} vs ${sideTag}`;
          const rateTxt = pointsPerMinute != null ? `${pointsPerMinute.toFixed(1)} pts/min` : 'live scoring';
          if (isOver) {
            const needPts = Math.max(0, Math.floor(line) + 1 - totalNow);
            trendDetail = `Scoring at ${rateTxt}, on pace for ~${liveProjTotal.toFixed(1)} pts (${fmtSigned(projectedEdgeVsLine, 1)} vs Over ${lineStr}); needs ${needPts} more pts over the last ${remMinsLabel}.`;
          } else {
            const roomLeft = Math.max(0, Math.ceil(line) - 1 - totalNow);
            trendDetail = `Scoring at ${rateTxt}, on pace for ~${liveProjTotal.toFixed(1)} pts (${fmtSigned(-projectedEdgeVsLine, 1)} vs Under ${lineStr}); needs teams to score ${roomLeft} or fewer pts in the last ${remMinsLabel}.`;
          }
        }
      }
    } else if ((betType === 'SPREAD' && line != null) || betType === 'ML') {
      const effectiveLine = betType === 'ML' ? 0 : line;
      const isHomePick = isHomeSelectionForGame(sel, rec, game);
      const pickedTeam = isHomePick
        ? game.home_team || parsedSel.team || 'Home'
        : game.away_team || parsedSel.team || 'Away';
      const pickedScore = isHomePick ? homeScore : awayScore;
      const oppScore = isHomePick ? awayScore : homeScore;
      const currentGameMargin = pickedScore - oppScore;
      const currentSpreadMargin = currentGameMargin + effectiveLine;
      const lineStr =
        betType === 'ML'
          ? 'ML'
          : `${effectiveLine > 0 ? '+' : ''}${Number(effectiveLine).toFixed(1).replace(/\.0$/, '')}`;

      if (isFinal) {
        projectedBetMargin = Number(currentSpreadMargin.toFixed(1));
        const absDiff = Math.abs(currentSpreadMargin).toFixed(1).replace(/\.0$/, '');
        if (currentSpreadMargin > 0) {
          trendVerdict = 'WON';
          trendLabel = 'Won';
          liveWinProb = 1;
          coverText = betType === 'ML' ? `Bet Won (+${absDiff} margin)` : `Covered by +${absDiff} pts`;
          coverTone = 'win';
          trendDetail = `${pickedTeam} finished ${currentGameMargin >= 0 ? `up ${currentGameMargin}` : `down ${Math.abs(currentGameMargin)}`}, winning the ${lineStr} bet.`;
        } else if (currentSpreadMargin === 0) {
          trendVerdict = 'PUSH';
          trendLabel = 'Push';
          liveWinProb = 0.5;
          coverText = 'Push (tie against line)';
          trendDetail = `${pickedTeam} landed directly on ${lineStr} (push/refund).`;
        } else {
          trendVerdict = 'LOST';
          trendLabel = 'Lost';
          liveWinProb = 0;
          coverText = betType === 'ML' ? `Bet Lost (-${absDiff})` : `Missed spread by ${absDiff} pts`;
          coverTone = 'loss';
          trendDetail = `${pickedTeam} finished ${currentGameMargin >= 0 ? `up ${currentGameMargin}` : `down ${Math.abs(currentGameMargin)}`}, falling ${absDiff} pts short of ${lineStr}.`;
        }
      } else if (isLive) {
        const liveProjMarginPick = isHomePick ? liveProjHomeMargin : -liveProjHomeMargin;
        const projectedCoverMargin = Number((liveProjMarginPick + effectiveLine).toFixed(1));
        projectedBetMargin = projectedCoverMargin;
        const sigmaSpreadRem = Math.max(1.5, 10.5 * Math.sqrt(remFrac));
        liveWinProb = Number(clamp(normalCdf(projectedCoverMargin / sigmaSpreadRem), 0.02, 0.98).toFixed(2));

        if (projectedCoverMargin >= 1.25) {
          trendVerdict = 'TRENDING_WIN';
          trendLabel = 'Trending to Win';
          coverTone = 'win';
        } else if (projectedCoverMargin <= -1.25) {
          trendVerdict = 'TRENDING_LOSE';
          trendLabel = 'Trending to Lose';
          coverTone = 'loss';
        } else {
          trendVerdict = 'TOSS_UP';
          trendLabel = 'Tight / Toss-Up';
          coverTone = 'tossup';
        }

        const pctTxt = `${Math.round(liveWinProb * 100)}%`;
        const projMarginStr = `${liveProjMarginPick >= 0 ? '+' : ''}${liveProjMarginPick.toFixed(1)}`;
        coverText = `${trendLabel} (${pctTxt}) · Pace ${projMarginStr} vs ${lineStr}`;

        const scoreStateStr =
          currentGameMargin > 0
            ? `leading by ${currentGameMargin}`
            : currentGameMargin < 0
              ? `trailing by ${Math.abs(currentGameMargin)}`
              : 'tied';
        const paceVerdictPhrase =
          projectedCoverMargin >= 0
            ? `on pace to cover by +${Math.abs(projectedCoverMargin).toFixed(1)} pts`
            : `on pace to miss ${lineStr} by ${Math.abs(projectedCoverMargin).toFixed(1)} pts`;
        trendDetail = `${pickedTeam} is currently ${scoreStateStr}, projecting to finish ${projMarginStr} (${paceVerdictPhrase}) with ${remMinsLabel} left.`;
      }
    }
  }

  if (!trendVerdict && hasScore && (isLive || isFinal)) {
    const mktTotal = toNum(game.total_line ?? game.total);
    const mktHomeSpread = toNum(game.home_spread ?? game.spread_home);
    const homeTeam = game.home_team || 'Home';
    const awayTeam = game.away_team || 'Away';

    if (isLive) {
      let totalTrend = '';
      if (mktTotal != null && liveProjTotal != null) {
        const totalDiff = liveProjTotal - mktTotal;
        const totalStr = Number(mktTotal).toFixed(1).replace(/\.0$/, '');
        totalTrend =
          totalDiff >= 1.5
            ? `Trending OVER ${totalStr} (Pace ~${liveProjTotal.toFixed(1)})`
            : totalDiff <= -1.5
              ? `Trending UNDER ${totalStr} (Pace ~${liveProjTotal.toFixed(1)})`
              : `On Total Pace ~${liveProjTotal.toFixed(1)} vs ${totalStr}`;
      }

      let spreadTrend = '';
      if (mktHomeSpread != null && liveProjHomeMargin != null) {
        const favTeam = mktHomeSpread <= 0 ? homeTeam : awayTeam;
        const dogTeam = mktHomeSpread <= 0 ? awayTeam : homeTeam;
        const favLine = mktHomeSpread <= 0 ? mktHomeSpread : -mktHomeSpread;
        const projFavMargin = mktHomeSpread <= 0 ? liveProjHomeMargin : -liveProjHomeMargin;
        const projFavCover = projFavMargin + favLine;
        const favLineStr = `${favLine > 0 ? '+' : ''}${Number(favLine).toFixed(1).replace(/\.0$/, '')}`;
        spreadTrend =
          projFavCover >= 1.25
            ? `${favTeam} ${favLineStr} Trending to Cover`
            : projFavCover <= -1.25
              ? `${dogTeam} Trending to Cover vs ${favTeam} ${favLineStr}`
              : `Spread Tight vs ${favTeam} ${favLineStr}`;
      }

      const combined = [totalTrend, spreadTrend].filter(Boolean);
      coverText = combined.length > 0 ? combined.join(' · ') : gameTrendText;
      trendLabel = totalTrend || spreadTrend || 'Live Pace';
      coverTone = 'neutral';
      const ratePart = pointsPerMinute != null ? `${pointsPerMinute.toFixed(1)} pts/min` : 'In progress';
      const projPart = `Proj Final: ${awayTeam} ${liveProjAwayScore} – ${homeTeam} ${liveProjHomeScore}`;
      trendDetail = spreadTrend ? `${ratePart} · ${projPart} (${spreadTrend})` : `${ratePart} · ${projPart}`;
    } else if (isFinal && (mktTotal != null || mktHomeSpread != null)) {
      const parts = [];
      if (mktTotal != null) {
        const totalStr = Number(mktTotal).toFixed(1).replace(/\.0$/, '');
        const resTag = totalNow > mktTotal ? 'OVER' : totalNow < mktTotal ? 'UNDER' : 'PUSH';
        parts.push(`Total ${totalNow} (${resTag} ${totalStr})`);
      }
      if (mktHomeSpread != null) {
        const homeCover = homeScore - awayScore + mktHomeSpread;
        const winnerCover = homeCover > 0 ? `${homeTeam} Covered` : homeCover < 0 ? `${awayTeam} Covered` : 'Spread Push';
        parts.push(winnerCover);
      }
      coverText = parts.join(' · ');
      trendLabel = 'Final Result';
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
    periodLabel: progress.periodLabel,
    elapsedMinutes: progress.elapsedMinutes,
    remainingMinutes: progress.remainingMinutes,
    totalGameMinutes: progress.totalGameMinutes,
    elapsedFraction: progress.elapsedFraction,
    progressPct: progress.progressPct,
    pointsPerMinute,
    liveProjTotal,
    liveProjHomeMargin,
    liveProjHomeScore,
    liveProjAwayScore,
    gameTrendText,
    trendVerdict,
    trendLabel,
    liveWinProb,
    trendDetail,
    projectedBetMargin,
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
      label: `${convCount}/${Math.max(convCount, activeSourceCount)} Models Agree`,
    });
  } else if (modelPct != null && modelPct > 0) {
    pills.push({
      id: 'weight',
      tone: 'blue',
      label: `${modelPct}% Model Weight`,
    });
  }

  if (sosMomShift && sosMomShift.pts >= 0.1) {
    pills.push({
      id: 'sos-mom',
      tone: 'emerald',
      label: `Form/Sched: ${sosMomShift.text}`,
    });
  }
  if (restSpotShift && restSpotShift.pts >= 0.1) {
    pills.push({
      id: 'rest-spot',
      tone: 'amber',
      label: `Rest Edge: ${restSpotShift.text}`,
    });
  }
  if (blowoutSigmaAdd >= 0.1) {
    pills.push({
      id: 'blowout',
      tone: 'amber',
      label: 'High Blowout Risk',
    });
  }
  if (isTotalBet && totalMove) {
    pills.push({
      id: 'total-move',
      tone: 'blue',
      label: `Line Moved: ${totalMove.text}`,
    });
  } else if (!isTotalBet && spreadMove) {
    pills.push({
      id: 'spread-move',
      tone: 'blue',
      label: `Line Moved: ${spreadMove.text}`,
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
