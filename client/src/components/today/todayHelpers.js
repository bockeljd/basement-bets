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

export const normalizeBoardTeamKey = (s) =>
  String(s || '')
    .toLowerCase()
    .trim()
    .replace(/\bnorth carolina state\b|\bn\.c\. state\b|\bn\.c\. st\.?\b|\bnc st\.?\b/g, 'nc state')
    .replace(/\bappalachian state\b|\bapp state\b|\bappalachian st\.?\b/g, 'appalachian state')
    .replace(/\bsouth carolina upstate\b|\bu\.s\.c\. upstate\b/g, 'usc upstate')
    .replace(/\blong island university\b|\bl\.i\.u\.?\b/g, 'liu')
    .replace(/\bse louisiana\b|\bs\.e\. louisiana\b|\bsoutheastern la\.?\b/g, 'southeastern louisiana')
    .replace(/\bse missouri st(?:ate)?\.?\b|\bsemo\b/g, 'southeast missouri state')
    .replace(/\bgrambling st(?:ate)?\.?\b/g, 'grambling')
    .replace(/\bwarner southern(?:\s+royals)?\b|\bwarner royals\b|\bwarner university\b/g, 'warner')
    .replace(/\bnicholls st(?:ate)?\.?\b/g, 'nicholls')
    .replace(/\bmcneese st(?:ate)?\.?\b/g, 'mcneese')
    .replace(/\bsam houston st(?:ate)?\.?\b/g, 'sam houston')
    .replace(/\bdelaware fightin(?:'|g)? blue hens\b/g, 'delaware blue hens')
    .replace(/\btenn(?:essee)?[-\s]martin\b/g, 'ut martin')
    .replace(/\bamerican university eagles\b/g, 'american eagles')
    .replace(/\bgeorge washington revolutionaries\b/g, 'george washington colonials')
    .replace(/\bsan jos[eé] state\b/g, 'san jose state')
    .replace(/\bstephen f\.? austin\b|\bsf austin\b/g, 'stephen f austin')
    .replace(/\bst\.?\s*francis\b/g, 'saint francis')
    .replace(/^st\.?\s+/g, 'saint ')
    .replace(/(^|\s)(?:mt\.?|mount)\s+st\.?\s+/g, '$1mount saint ')
    .replace(/[^a-z0-9]/g, '');

export const buildCachedAnalysisResult = (game, cachedMeta) => {
  if (!game || !cachedMeta) return null;
  const ctx = cachedMeta.context && typeof cachedMeta.context === 'object' ? cachedMeta.context : null;
  const rec = cachedMeta.rec && typeof cachedMeta.rec === 'object' ? cachedMeta.rec : null;
  const hasRec = Boolean(cachedMeta.isActionable && rec);
  const blockReason = !hasRec ? (cachedMeta.reason || rec?.reason || ctx?.reason || null) : null;
  return {
    event_id: game.id,
    recommendations: hasRec ? [rec] : [],
    context: ctx || undefined,
    outputs: ctx
      ? {
          mu_spread: ctx.fair_spread_home ?? ctx.mu_spread_power ?? null,
          mu_total: ctx.fair_total ?? ctx.mu_total_power ?? null,
        }
      : undefined,
    signals: rec?.signals || ctx?.signals || undefined,
    no_bet_reason: blockReason,
    block_reason: blockReason,
    headline: cachedMeta.reason || rec?.reason || undefined,
    analyzed_at: cachedMeta.analyzedAt || null,
    model_version: cachedMeta.model_version || null,
    neutral_site: game.neutral_site,
    venue: game.venue,
    venue_city: game.venue_city,
    venue_state: game.venue_state,
    _fromCache: true,
    _cachedAt: cachedMeta.analyzedAt || null,
  };
};

export const makeMatchupKey = (dayEt, away, home) => {
  if (!dayEt || !away || !home) return '';
  return `${dayEt}|${normalizeBoardTeamKey(away)}|${normalizeBoardTeamKey(home)}`;
};

export const lookupTopPickForGame = (game, rowTopPicks = {}, rowTopPicksByKey = {}) => {
  if (!game) return null;
  if (rowTopPicks[game.id]) return rowTopPicks[game.id];
  const day = game.day_et || (game.start_time ? String(game.start_time).slice(0, 10) : '');
  const k = makeMatchupKey(day, game.away_team, game.home_team);
  if (k && rowTopPicksByKey[k]) return rowTopPicksByKey[k];
  const revK = makeMatchupKey(day, game.home_team, game.away_team);
  return revK ? rowTopPicksByKey[revK] || null : null;
};

/**
 * Deduplicate board games using unordered matchup keys so reversed home/away
 * neutral-site feeds (e.g. ESPN vs Action Network) collapse to the richer priced row.
 */
export const dedupeBoardGames = (games) => {
  if (!Array.isArray(games) || games.length === 0) return [];

  const rowScore = (g) => {
    const hasOdds =
      g?.home_spread != null || g?.total_line != null || g?.ml_home_odds != null || g?.ml_away_odds != null ? 10 : 0;
    const idStr = String(g?.id || '').toLowerCase();
    const srcScore = idStr.startsWith('action:') ? 2 : idStr.startsWith('espn:') ? 1 : 0;
    return hasOdds + srcScore;
  };

  const bestByKey = new Map();
  const order = [];
  for (const g of games) {
    if (!g) continue;
    const league = String(g.sport || g.league || 'NCAAM').toUpperCase();
    const day = g.day_et || (g.start_time ? String(g.start_time).slice(0, 10) : '');
    const tA = normalizeBoardTeamKey(g.away_team);
    const tB = normalizeBoardTeamKey(g.home_team);
    if (!tA || !tB) {
      const fallbackKey = String(g.id || order.length);
      if (!bestByKey.has(fallbackKey)) {
        bestByKey.set(fallbackKey, g);
        order.push(fallbackKey);
      }
      continue;
    }
    const [first, second] = tA <= tB ? [tA, tB] : [tB, tA];
    const key = `${league}|${day}|${first}|${second}`;
    if (!bestByKey.has(key)) {
      bestByKey.set(key, g);
      order.push(key);
    } else if (rowScore(g) > rowScore(bestByKey.get(key))) {
      bestByKey.set(key, g);
    }
  }
  return order.map((k) => bestByKey.get(k));
};

export const normalizeMovementTag = (tag) => {
  const t = String(tag || '').toLowerCase();
  if (t === 'rlm_confirmed') return { label: 'Pro Money Line Move', tone: 'emerald' };
  if (t === 'sharp_backing') return { label: 'Big Money Backing', tone: 'emerald' };
  if (t === 'sharp_price_edge') return { label: 'Better Line Than Sharp Books', tone: 'emerald' };
  if (t === 'lagging_book_edge') return { label: 'Better Line vs. Market', tone: 'emerald' };
  if (t === 'smart_risk_high_return') return { label: 'Smart Risk · 0.5u', tone: 'indigo' };
  if (t === 'first_half_market') return { label: '1st Half Line', tone: 'blue' };
  if (t === 'injury_line_adjusted') return { label: 'Injury Priced In', tone: 'amber' };
  if (t === 'contra_sharp_money') return { label: 'Against Big Money', tone: 'rose' };
  if (t === 'contra_sharp_line') return { label: 'Behind Sharp Books', tone: 'rose' };
  if (t.startsWith('reverse_steam=')) return { label: 'Market Steamed Opposite', tone: 'rose' };
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

export const hasTop6RiskFlag = (rec) => {
  if (!rec) return false;
  if (rec.top6_eligible === false) return true;
  const rawTags = rec.movement_tags || rec.sanity_reasons;
  const tags = Array.isArray(rawTags)
    ? rawTags
    : typeof rawTags === 'string'
      ? rawTags.split(',')
      : [];
  return tags.some((t) => {
    const low = String(t || '').trim().toLowerCase();
    return low === 'contra_sharp_money' || low === 'contra_sharp_line' || low.startsWith('reverse_steam=');
  });
};

export const getRecQualityScore = (rec) => {
  if (!rec) return -999;

  const evRaw = getRecEv(rec);
  const ev = evRaw !== null && Number.isFinite(evRaw) ? evRaw : 0;
  const effEv =
    ev <= 0.085
      ? ev
      : ev <= 0.105
        ? 0.085 + (ev - 0.085) * 0.30
        : 0.085 + 0.020 * 0.30 - (ev - 0.105) * 0.20;
  let score = effEv;

  const lb10 = rec.win_prob_lb10 === null || rec.win_prob_lb10 === undefined || rec.win_prob_lb10 === ''
    ? NaN
    : Number(rec.win_prob_lb10);
  if (Number.isFinite(lb10)) {
    score += Math.max(0, lb10 - 0.52) * 0.35;
  } else {
    const confNum = Number(rec.confidence_0_100 ?? (typeof rec.confidence === 'number' ? rec.confidence : NaN));
    if (Number.isFinite(confNum)) {
      const scaled = confNum <= 1 ? confNum * 100 : confNum;
      score += Math.max(0, scaled - 55) * 0.0004;
    }
  }

  const mkt = String(rec.bet_type || rec.market_type || rec.market || '').toUpperCase();
  const sel = String(rec.selection || rec.side || '').toUpperCase();
  const rawLine = rec.market_line ?? rec.bet_line ?? rec.line;
  const parsedLine = rawLine !== null && rawLine !== undefined && rawLine !== '' ? Number(rawLine) : NaN;
  if (mkt.includes('TOTAL')) {
    if (sel.includes('UNDER')) score += 0.003;
    if (Number.isFinite(parsedLine)) {
      const totLine = Math.abs(parsedLine);
      if (totLine >= 138 && totLine <= 156) score += 0.004;
    }
  } else if (mkt.includes('SPREAD')) {
    if (Number.isFinite(parsedLine)) {
      const absLine = Math.abs(parsedLine);
      if (absLine < 6) score += 0.005;
      else if (absLine >= 6 && absLine < 14) score += 0.003;
      else if (absLine >= 14 && absLine < 22) score -= 0.018;
      else if (absLine >= 22) score -= 0.03;

      const sideHint = String(rec.side || '').trim().toLowerCase();
      let isAway = null;
      if (sideHint === 'away' || sideHint === 'home') {
        isAway = sideHint === 'away';
      } else {
        const selLow = String(rec.selection || rec.pick || '').trim().toLowerCase();
        const awayTeam = String(rec.away_team || '').trim().toLowerCase();
        const homeTeam = String(rec.home_team || '').trim().toLowerCase();
        if (awayTeam && selLow.startsWith(awayTeam)) isAway = true;
        else if (homeTeam && selLow.startsWith(homeTeam)) isAway = false;
      }

      if (parsedLine > 0) score += isAway ? 0.007 : 0.005;
      else if (parsedLine < 0 && isAway) score -= 0.016;
    }
  }

  const rawAgree = mkt.includes('TOTAL')
    ? (rec.conviction_sources_total ?? rec.signals?.adjustments?.conviction_sources_total)
    : (rec.conviction_sources ?? rec.signals?.adjustments?.conviction_sources);
  const agreeN = rawAgree !== null && rawAgree !== undefined && rawAgree !== '' ? Number(rawAgree) : NaN;
  if (Number.isFinite(agreeN)) {
    if (agreeN >= 3) score += 0.012;
    else if (agreeN === 2) score += 0.006;
  }

  const rawTags = rec.movement_tags || rec.sanity_reasons;
  const tagList = Array.isArray(rawTags)
    ? rawTags
    : typeof rawTags === 'string'
      ? rawTags.split(',')
      : [];
  const tags = tagList.map((t) => String(t || '').trim().toLowerCase()).filter(Boolean);
  if (tags.includes('sharp_backing')) score += 0.012;
  if (tags.includes('rlm_confirmed')) score += 0.006;
  if (tags.includes('sharp_price_edge')) score += 0.008;
  if (tags.includes('contra_sharp_money')) score -= 0.03;
  if (tags.includes('contra_sharp_line')) score -= 0.018;
  if (tags.some((t) => t.startsWith('reverse_steam='))) score -= 0.02;
  const isSmartRisk =
    Boolean(rec.is_smart_risk) ||
    String(rec.risk_tier || '').trim().toUpperCase() === 'SMART_RISK' ||
    tags.includes('smart_risk_high_return');
  if (isSmartRisk) score -= 0.015;

  return score;
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
  const isSmartRisk =
    Boolean(rec.is_smart_risk) ||
    String(rec.risk_tier || '').trim().toUpperCase() === 'SMART_RISK';
  if (isSmartRisk) {
    return {
      tier: 'SMART_RISK',
      score,
      sortScore: Math.max(score ?? 52, 52),
      badgeCls: 'bg-indigo-500/15 text-indigo-200 border-indigo-400/40',
    };
  }
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
  const isFirstHalf = betTypeRaw === 'SPREAD_1H' || betTypeRaw === 'TOTAL_1H';
  const isTotal = betTypeRaw === 'TOTAL' || betTypeRaw === 'TOTAL_1H' || /\b(OVER|UNDER)\b/i.test(String(rec?.selection || ''));
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
    sideLabel = isFirstHalf ? '1H Combined Points' : 'Combined Points';
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
    sideLabel = pickedHome
      ? `${home} ${isFirstHalf ? '1H ' : ''}Spread`
      : `${away} ${isFirstHalf ? '1H ' : ''}Spread`;
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
  if (!isFirstHalf) {
    const tvLine = toSide(mode === 'TOTAL' ? sig.torvik?.fair_total : sig.torvik?.fair_spread_home);
    const hsLine = toSide(mode === 'TOTAL' ? sig.haslametrics?.fair_total : sig.haslametrics?.fair_spread_home);
    const kpLine = toSide(mode === 'TOTAL' ? sig.kenpom?.fair_total : sig.kenpom?.fair_spread_home);
    if (tvLine != null) sources.push({ id: 'torvik', label: 'BartTorvik', line: Number(tvLine.toFixed(1)), color: '#0ea5e9' });
    if (hsLine != null) sources.push({ id: 'hasla', label: 'Haslametrics', line: Number(hsLine.toFixed(1)), color: '#8b5cf6' });
    if (kpLine != null) sources.push({ id: 'kenpom', label: 'KenPom', line: Number(kpLine.toFixed(1)), color: '#10b981' });
  }

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

export const interpolateLiveCalProb = (pRaw, points, blendWeight = 0.5) => {
  const pVal = Number(pRaw);
  if (!Number.isFinite(pVal)) return pRaw;
  if (!Array.isArray(points) || points.length < 2) return pVal;
  const clean = points
    .filter((pt) => pt && pt.p != null && pt.p_cal != null)
    .map((pt) => ({ p: Number(pt.p), pCal: Number(pt.p_cal) }))
    .filter((pt) => Number.isFinite(pt.p) && Number.isFinite(pt.pCal))
    .sort((a, b) => a.p - b.p);
  if (clean.length < 2) return pVal;

  let pCal = pVal;
  if (pVal <= clean[0].p) {
    pCal = clamp(clean[0].pCal, 0, 1);
  } else if (pVal >= clean[clean.length - 1].p) {
    pCal = clamp(clean[clean.length - 1].pCal, 0, 1);
  } else {
    for (let i = 1; i < clean.length; i += 1) {
      if (pVal <= clean[i].p) {
        const x0 = clean[i - 1].p;
        const x1 = clean[i].p;
        const y0 = clean[i - 1].pCal;
        const y1 = clean[i].pCal;
        const t = x1 === x0 ? 1 : (pVal - x0) / (x1 - x0);
        pCal = clamp(y0 + t * (y1 - y0), 0, 1);
        break;
      }
    }
  }
  const w = clamp(Number(blendWeight), 0, 1);
  return clamp((1 - w) * pVal + w * pCal, 0.01, 0.99);
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
  const isFirstHalfBet = betTypeRaw.includes('1H') || /\b1H\b/i.test(sel);
  const isTotalBet = betTypeRaw === 'TOTAL' || betTypeRaw === 'TOTAL_1H' || /\b(OVER|UNDER)\b/i.test(sel);
  const isMlBet = betTypeRaw === 'ML' || betTypeRaw === 'MONEYLINE' || /\b(ML|MONEYLINE)\b/i.test(sel);
  const betType = isTotalBet ? 'TOTAL' : isMlBet ? 'ML' : betTypeRaw.replace(/_1H$/, '') || 'SPREAD';

  const pregameFullTotal =
    toNum(
      context?.fair_total ??
        (!isFirstHalfBet && isTotalBet ? rec?.fair_line : null) ??
        (!isFirstHalfBet ? rec?.market_line : null) ??
        game?.total_line ??
        game?.total
    ) ?? 142;

  const pregameTotal = isFirstHalfBet
    ? (toNum(isTotalBet ? (rec?.fair_line ?? rec?.market_line) : null) ?? Number((pregameFullTotal * 0.47).toFixed(1)))
    : pregameFullTotal;

  const isHomePickForSpread = rec ? isHomeSelectionForGame(sel, rec, game) : true;
  const fallbackSpreadHome =
    rec && !isTotalBet && !isMlBet && toNum(rec?.market_line ?? extractTeamAndLineFromSelection(sel).line) != null
      ? (isHomePickForSpread
          ? toNum(rec?.market_line ?? extractTeamAndLineFromSelection(sel).line)
          : -toNum(rec?.market_line ?? extractTeamAndLineFromSelection(sel).line))
      : 0;
  const pregameHomeSpreadFull =
    toNum(context?.fair_spread_home ?? game?.home_spread ?? game?.spread_home) ?? fallbackSpreadHome;
  const pregameHomeMargin = isFirstHalfBet ? pregameHomeSpreadFull * -0.5 : -pregameHomeSpreadFull;

  const fullProgress = estimateLiveGameProgress(game, pregameFullTotal);
  const halfMins = fullProgress.totalGameMinutes > 0 ? fullProgress.totalGameMinutes / 2 : 20;
  const isSecondHalfOrLater =
    isFirstHalfBet &&
    (isFinal ||
      isHalftime ||
      fullProgress.elapsedMinutes >= halfMins - 0.01 ||
      (toNum(game?.period) != null && toNum(game?.period) >= 2));

  const progress = isFirstHalfBet
    ? {
        ...fullProgress,
        totalGameMinutes: halfMins,
        elapsedMinutes: Number(Math.min(halfMins, fullProgress.elapsedMinutes).toFixed(2)),
        remainingMinutes: isSecondHalfOrLater
          ? 0
          : Number(Math.max(0, halfMins - fullProgress.elapsedMinutes).toFixed(2)),
        elapsedFraction: isSecondHalfOrLater
          ? 1
          : clamp(fullProgress.elapsedMinutes / Math.max(1, halfMins), 0.04, 0.99),
        progressPct: isSecondHalfOrLater
          ? 100
          : Math.round(clamp(fullProgress.elapsedMinutes / Math.max(1, halfMins), 0.04, 0.99) * 100),
      }
    : fullProgress;

  // For 1H bets once 1st half is over: use 1H scores if available (or halftime score), else avoid grading 2H score vs 1H line
  const homeScore1H = toNum(game?.home_score_1h) ?? (isHalftime ? homeScore : null);
  const awayScore1H = toNum(game?.away_score_1h) ?? (isHalftime ? awayScore : null);
  const effectiveHomeScore = isFirstHalfBet && isSecondHalfOrLater ? homeScore1H : homeScore;
  const effectiveAwayScore = isFirstHalfBet && isSecondHalfOrLater ? awayScore1H : awayScore;
  const effectiveIsFinal = isFirstHalfBet ? isSecondHalfOrLater && effectiveHomeScore != null && effectiveAwayScore != null : isFinal;
  const effectiveIsLive = isFirstHalfBet ? isLive && !isSecondHalfOrLater : isLive;

  let totalNow = null;
  let pointsPerMinute = null;
  let liveProjTotal = null;
  let liveProjTotalReg = null;
  let liveProjHomeMargin = null;
  let liveProjHomeScore = null;
  let liveProjAwayScore = null;
  let latePaceAdj = 0;
  let otProb = 0;
  let otExpectedPts = 0;
  let gameTrendText = '';

  const lt = game?.live_trend || {};
  const firstHalfShare = clamp(toNum(lt.first_half_share) ?? 0.47, 0.4, 0.54);
  const lateFoulBoostPts = Math.max(0, toNum(lt.late_foul_boost_pts) ?? 3.5);
  const lateBlowoutDragPts = Math.max(0, toNum(lt.late_blowout_drag_pts) ?? 2.5);
  const otExtraPts = Math.max(0, toNum(lt.ot_extra_pts) ?? 15.5);
  const otProbScale = Math.max(0, toNum(lt.ot_prob_scale) ?? 1.0);
  const sigmaSpreadBaseFull = toNum(lt.sigma_spread_rem) ?? 10.5;
  const inOvertime =
    (toNum(game?.period) != null && toNum(game?.period) > 2) ||
    /\bOT\b/i.test(String(game?.status_detail || game?.period_label || ''));

  const expectedCbbScoringShare = (ef) => {
    const c = clamp(ef, 0, 1);
    if (c <= 0.5) return (c / 0.5) * firstHalfShare;
    return firstHalfShare + ((c - 0.5) / 0.5) * (1 - firstHalfShare);
  };

  if (effectiveHomeScore != null && effectiveAwayScore != null) {
    totalNow = effectiveHomeScore + effectiveAwayScore;
    if (effectiveIsFinal) {
      pointsPerMinute =
        progress.elapsedMinutes > 0 ? Number((totalNow / progress.elapsedMinutes).toFixed(2)) : null;
      liveProjTotal = totalNow;
      liveProjTotalReg = totalNow;
      liveProjHomeMargin = effectiveHomeScore - effectiveAwayScore;
      liveProjHomeScore = effectiveHomeScore;
      liveProjAwayScore = effectiveAwayScore;
      const finPrefix = isFirstHalfBet ? '1H Final' : 'Final';
      gameTrendText = `${finPrefix}: ${game.away_team || 'Away'} ${effectiveAwayScore} – ${game.home_team || 'Home'} ${effectiveHomeScore} (${totalNow} pts)`;
    } else if (effectiveIsLive) {
      const elapsedFrac = progress.elapsedFraction;
      const remFrac = Math.max(0, 1 - elapsedFrac);
      const liveWeightScale = toNum(lt.live_weight_scale) ?? 0.85;
      const maxLiveWeight = liveWeightScale > 0.88 ? 0.85 : 0.8;
      const liveWeight = clamp(elapsedFrac * liveWeightScale, 0.15, maxLiveWeight);
      pointsPerMinute =
        progress.elapsedMinutes > 0.5 ? Number((totalNow / progress.elapsedMinutes).toFixed(2)) : null;

      const currentHomeMargin = effectiveHomeScore - effectiveAwayScore;
      const marginCap = isFirstHalfBet ? 22 : 35;
      const rawPaceHomeMargin = clamp(currentHomeMargin / Math.max(0.04, elapsedFrac), -marginCap, marginCap);
      const blendedMarginRate = liveWeight * rawPaceHomeMargin + (1 - liveWeight) * pregameHomeMargin;
      liveProjHomeMargin = Number((currentHomeMargin + blendedMarginRate * remFrac).toFixed(1));

      if (isFirstHalfBet) {
        const preTarget1H = pregameTotal > 95 ? pregameTotal * firstHalfShare : pregameTotal;
        const rawPaceTotal = clamp(totalNow / Math.max(0.04, elapsedFrac), 30, 125);
        const blendedTotalRate = liveWeight * rawPaceTotal + (1 - liveWeight) * preTarget1H;
        liveProjTotal = Number(Math.max(totalNow, totalNow + blendedTotalRate * remFrac).toFixed(1));
        liveProjTotalReg = liveProjTotal;
      } else {
        const scoredShare = clamp(expectedCbbScoringShare(elapsedFrac), 0.04, 0.99);
        const remShare = Math.max(0, 1 - scoredShare);
        const rawPaceTotal = clamp(totalNow / scoredShare, 75, 235);
        const blendedTotalRate = liveWeight * rawPaceTotal + (1 - liveWeight) * pregameTotal;
        const baseProjTotal = Math.max(totalNow, totalNow + blendedTotalRate * remShare);

        // Late-game fouling surge (close games) vs. blowout slowdown in final ~5 minutes
        const remMins = Math.max(0, progress.remainingMinutes);
        if (!inOvertime && remMins > 0.05 && remMins < 5.0) {
          const lateWindow = clamp((5.0 - remMins) / 4.0, 0, 1);
          const timeTaper = Math.min(1.0, remMins / 1.5);
          const foulTimeFactor = lateWindow * timeTaper;
          const absMargin = Math.abs(currentHomeMargin);
          if (absMargin >= 1 && absMargin <= 9) {
            const closeness = Math.max(0, 1 - Math.abs(absMargin - 4.0) / 5.0);
            latePaceAdj = Number((lateFoulBoostPts * foulTimeFactor * closeness).toFixed(2));
          } else if (absMargin >= 15) {
            const blowoutIntensity = clamp((absMargin - 14.0) / 10.0, 0, 1);
            latePaceAdj = Number((-lateBlowoutDragPts * foulTimeFactor * blowoutIntensity).toFixed(2));
          }
        }
        liveProjTotalReg = Number(Math.max(totalNow, baseProjTotal + latePaceAdj).toFixed(1));

        // Overtime probability bump for close 2nd-half games
        if (!inOvertime && elapsedFrac >= 0.55 && remMins > 0.05 && otProbScale > 0) {
          const sigmaSpNow = Math.max(1.5, sigmaSpreadBaseFull * Math.sqrt(Math.max(0.02, remFrac)));
          const pTieRaw =
            normalCdf((0.5 - liveProjHomeMargin) / sigmaSpNow) -
            normalCdf((-0.5 - liveProjHomeMargin) / sigmaSpNow);
          otProb = Number(clamp(pTieRaw * otProbScale, 0, 0.35).toFixed(4));
          otExpectedPts = Number((otProb * otExtraPts).toFixed(2));
        }

        liveProjTotal = Number(Math.max(totalNow, liveProjTotalReg + otExpectedPts).toFixed(1));
      }

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
      liveProjHomeScore = Math.max(effectiveHomeScore, Math.round(effectiveHomeScore + remHome));
      liveProjAwayScore = Math.max(effectiveAwayScore, Math.round(effectiveAwayScore + remAway));
      const pacePrefix = isFirstHalfBet ? '1H Pace' : 'Live Pace';
      gameTrendText = `${pacePrefix}: ${game.away_team || 'Away'} ${liveProjAwayScore} – ${game.home_team || 'Home'} ${liveProjHomeScore} (~${Math.round(liveProjTotal)} pts)`;
    }
  }

  let coverText = '';
  let coverTone = 'neutral';
  let trendVerdict = null;
  let trendLabel = '';
  let liveWinProb = null;
  let trendDetail = '';
  let projectedBetMargin = null;

  if (isFirstHalfBet && isSecondHalfOrLater && !effectiveIsFinal && rec) {
    trendVerdict = 'PENDING_1H';
    trendLabel = '1st Half Complete';
    coverText = '1st Half Complete';
    trendDetail = '1st half has finished; awaiting official 1st-half score grading.';
  } else if (effectiveHomeScore != null && effectiveAwayScore != null && rec && (effectiveIsLive || effectiveIsFinal)) {
    const parsedSel = extractTeamAndLineFromSelection(sel);
    const line = toNum(rec.market_line ?? rec.line ?? parsedSel.line);
    const remFrac = Math.max(0.02, 1 - progress.elapsedFraction);
    const remMinsVal = Math.max(0, progress.remainingMinutes);
    const remMinsLabel =
      remMinsVal < 1
        ? `${Math.max(1, Math.round(remMinsVal * 60))} sec`
        : remMinsVal < 5
          ? `${remMinsVal.toFixed(1)} min`
          : `${Math.round(remMinsVal)} min`;

    if (betType === 'TOTAL' && line != null) {
      const isOver = /OVER|^O\b/i.test(sel || String(rec.side || ''));
      const lineStr = Number(line).toFixed(1).replace(/\.0$/, '');
      const sideTag = isOver ? `${isFirstHalfBet ? '1H ' : ''}O ${lineStr}` : `${isFirstHalfBet ? '1H ' : ''}U ${lineStr}`;

      if (effectiveIsFinal) {
        const diff = totalNow - line;
        projectedBetMargin = Number((isOver ? diff : -diff).toFixed(1));
        if ((isOver && diff > 0) || (!isOver && diff < 0)) {
          trendVerdict = 'WON';
          trendLabel = 'Won';
          liveWinProb = 1;
          coverText = `Bet Won (${totalNow} ${isFirstHalfBet ? '1H' : 'total'} pts vs ${sideTag})`;
          coverTone = 'win';
          trendDetail = `${isFirstHalfBet ? '1st half' : 'Final'} total finished at ${totalNow} pts, clearing ${sideTag} by ${Math.abs(diff).toFixed(1)} pts.`;
        } else if (diff === 0) {
          trendVerdict = 'PUSH';
          trendLabel = 'Push';
          liveWinProb = 0.5;
          coverText = `Push (${totalNow} ${isFirstHalfBet ? '1H' : 'total'} pts)`;
          trendDetail = `${isFirstHalfBet ? '1st half' : 'Final'} total landed on ${totalNow} pts (exact push/refund).`;
        } else {
          trendVerdict = 'LOST';
          trendLabel = 'Lost';
          liveWinProb = 0;
          coverText = `Bet Lost (${totalNow} ${isFirstHalfBet ? '1H' : 'total'} pts vs ${sideTag})`;
          coverTone = 'loss';
          trendDetail = `${isFirstHalfBet ? '1st half' : 'Final'} total finished at ${totalNow} pts, missing ${sideTag} by ${Math.abs(diff).toFixed(1)} pts.`;
        }
      } else if (effectiveIsLive) {
        if (isOver && totalNow > line) {
          trendVerdict = 'TRENDING_WIN';
          trendLabel = 'Trending to Win';
          liveWinProb = 0.99;
          projectedBetMargin = Number((liveProjTotal - line).toFixed(1));
          coverTone = 'win';
          coverText = `Already Cashed (99%) · ${totalNow} > ${lineStr}`;
          trendDetail = `Already over ${lineStr} with ${totalNow} combined pts and ${remMinsLabel} left${isFirstHalfBet ? ' in 1H' : ''} — bet is locked in.`;
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
          const sigmaTotalBaseFull = toNum(game?.live_trend?.sigma_total_rem) ?? 13.5;
          const sigmaTotalBase = isFirstHalfBet ? sigmaTotalBaseFull * Math.SQRT1_2 : sigmaTotalBaseFull;
          const sigmaTotalRem = Math.max(1.5, sigmaTotalBase * Math.sqrt(remFrac));
          let rawLiveProb;
          if (!isFirstHalfBet && otProb > 0.01 && liveProjTotalReg != null) {
            const regMargin = isOver ? liveProjTotalReg - line : line - liveProjTotalReg;
            const otMargin = isOver
              ? liveProjTotalReg + otExtraPts - line
              : line - (liveProjTotalReg + otExtraPts);
            const pReg = normalCdf(regMargin / sigmaTotalRem);
            const pOt = normalCdf(otMargin / Math.sqrt(sigmaTotalRem * sigmaTotalRem + 16));
            rawLiveProb = clamp((1 - otProb) * pReg + otProb * pOt, 0.02, 0.98);
          } else {
            rawLiveProb = clamp(normalCdf(projectedEdgeVsLine / sigmaTotalRem), 0.02, 0.98);
          }
          liveWinProb = Number(
            interpolateLiveCalProb(rawLiveProb, game?.live_trend?.calibration_points, 0.5).toFixed(2)
          );

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
          const remSuffix = isFirstHalfBet ? ` in 1H` : '';
          const contextTags = [];
          if (!isFirstHalfBet && latePaceAdj >= 0.75) contextTags.push('late-foul surge');
          else if (!isFirstHalfBet && latePaceAdj <= -0.75) contextTags.push('blowout pace');
          if (!isFirstHalfBet && otProb >= 0.06) contextTags.push(`${Math.round(otProb * 100)}% OT chance`);
          const contextNote = contextTags.length > 0 ? ` (${contextTags.join(', ')})` : '';
          if (isOver) {
            const needPts = Math.max(0, Math.floor(line) + 1 - totalNow);
            trendDetail = `Scoring at ${rateTxt}, on pace for ~${liveProjTotal.toFixed(1)} ${isFirstHalfBet ? '1H ' : ''}pts${contextNote} (${fmtSigned(projectedEdgeVsLine, 1)} vs ${isFirstHalfBet ? '1H ' : ''}Over ${lineStr}); needs ${needPts} more pts over the last ${remMinsLabel}${remSuffix}.`;
          } else {
            const roomLeft = Math.max(0, Math.ceil(line) - 1 - totalNow);
            trendDetail = `Scoring at ${rateTxt}, on pace for ~${liveProjTotal.toFixed(1)} ${isFirstHalfBet ? '1H ' : ''}pts${contextNote} (${fmtSigned(-projectedEdgeVsLine, 1)} vs ${isFirstHalfBet ? '1H ' : ''}Under ${lineStr}); needs teams to score ${roomLeft} or fewer pts in the last ${remMinsLabel}${remSuffix}.`;
          }
        }
      }
    } else if ((betType === 'SPREAD' && line != null) || betType === 'ML') {
      const effectiveLine = betType === 'ML' ? 0 : line;
      const isHomePick = isHomeSelectionForGame(sel, rec, game);
      const pickedTeam = isHomePick
        ? game.home_team || parsedSel.team || 'Home'
        : game.away_team || parsedSel.team || 'Away';
      const pickedScore = isHomePick ? effectiveHomeScore : effectiveAwayScore;
      const oppScore = isHomePick ? effectiveAwayScore : effectiveHomeScore;
      const currentGameMargin = pickedScore - oppScore;
      const currentSpreadMargin = currentGameMargin + effectiveLine;
      const lineStr =
        betType === 'ML'
          ? 'ML'
          : `${effectiveLine > 0 ? '+' : ''}${Number(effectiveLine).toFixed(1).replace(/\.0$/, '')}`;

      if (effectiveIsFinal) {
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
      } else if (effectiveIsLive) {
        const liveProjMarginPick = isHomePick ? liveProjHomeMargin : -liveProjHomeMargin;
        const projectedCoverMargin = Number((liveProjMarginPick + effectiveLine).toFixed(1));
        projectedBetMargin = projectedCoverMargin;
        const sigmaSpreadBaseFull = toNum(game?.live_trend?.sigma_spread_rem) ?? 10.5;
        const sigmaSpreadBase = isFirstHalfBet ? sigmaSpreadBaseFull * Math.SQRT1_2 : sigmaSpreadBaseFull;
        const sigmaSpreadRem = Math.max(1.2, sigmaSpreadBase * Math.sqrt(remFrac));
        const rawLiveProb = clamp(normalCdf(projectedCoverMargin / sigmaSpreadRem), 0.02, 0.98);
        liveWinProb = Number(
          interpolateLiveCalProb(rawLiveProb, game?.live_trend?.calibration_points, 0.5).toFixed(2)
        );

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
      const projPart =
        liveProjAwayScore != null && liveProjHomeScore != null
          ? `Proj Final: ${awayTeam} ${liveProjAwayScore} – ${homeTeam} ${liveProjHomeScore}`
          : '';
      trendDetail = projPart
        ? (spreadTrend ? `${ratePart} · ${projPart} (${spreadTrend})` : `${ratePart} · ${projPart}`)
        : ratePart;
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
    isFirstHalfBet,
    isBetSettled: effectiveIsFinal,
    hasScore,
    homeScore,
    awayScore,
    homeScore1H,
    awayScore1H,
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
    latePaceAdj,
    otProb,
    otExpectedPts,
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

  // NCAAM research-backed spot context pills (surface immediately after consensus/weight so card slice keeps them)
  const spotSport = String(game?.sport || rec?.sport || 'NCAAM').toUpperCase();
  if (spotSport === 'NCAAM' || spotSport === 'NCAAB') {
    const rawSpotLine = rec?.market_line ?? rec?.bet_line ?? rec?.line;
    const spotLine =
      rawSpotLine !== null && rawSpotLine !== undefined && rawSpotLine !== ''
        ? Number(rawSpotLine)
        : NaN;
    if (Number.isFinite(spotLine)) {
      if (isTotalBet) {
        const totLine = Math.abs(spotLine);
        const isUnder = /\bUNDER\b/i.test(String(rec?.side || rec?.selection || rec?.pick || ''));
        if (totLine >= 140 && totLine < 152) {
          pills.push({ id: 'spot-zone', tone: 'emerald', label: 'Mid-Total Sweet Spot' });
        } else if (totLine >= 152 && isUnder) {
          pills.push({ id: 'spot-zone', tone: 'emerald', label: '152+ Under Value' });
        }
      } else if (betType === 'SPREAD') {
        const sideHint = String(rec?.side || '').trim().toLowerCase();
        let isAway = null;
        if (sideHint === 'away' || sideHint === 'home') {
          isAway = sideHint === 'away';
        } else {
          const selLow = String(rec?.selection || rec?.pick || '').trim().toLowerCase();
          const aLow = String(game?.away_team || '').trim().toLowerCase();
          const hLow = String(game?.home_team || '').trim().toLowerCase();
          if (aLow && selLow.startsWith(aLow)) isAway = true;
          else if (hLow && selLow.startsWith(hLow)) isAway = false;
        }
        if (spotLine > 0 && isAway === true) {
          pills.push({ id: 'spot-role', tone: 'emerald', label: 'Road Dog Sweet Spot' });
        } else if (spotLine > 0 && isAway === false) {
          pills.push({ id: 'spot-role', tone: 'emerald', label: 'Home Dog Value' });
        } else if (spotLine < 0 && isAway === true) {
          pills.push({ id: 'spot-role', tone: 'amber', label: 'Road Fav (High Bar)' });
        }
      }
    }
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

  const sharpEdge = toNum(rec?.sharp_edge_pts);
  const recTags = Array.isArray(rec?.movement_tags) ? rec.movement_tags : [];
  if (sharpEdge != null && sharpEdge >= 0.5) {
    pills.push({
      id: 'sharp-line-edge',
      tone: 'emerald',
      label: `Beats Sharp Line (+${sharpEdge.toFixed(1)})`,
    });
  } else if (
    (sharpEdge != null && sharpEdge <= -1.0) ||
    recTags.some((t) => String(t || '').trim().toLowerCase() === 'contra_sharp_line')
  ) {
    pills.push({
      id: 'contra-sharp-line',
      tone: 'amber',
      label: sharpEdge != null ? `Sharp Line Against (${sharpEdge.toFixed(1)})` : 'Sharp Line Against',
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

export const getRecommendedBetSize = (rec, bankroll = null) => {
  if (!rec) return null;
  const parsePos = (v) => {
    const n = Number(v);
    return Number.isFinite(n) && n > 0 ? n : null;
  };
  let units = parsePos(rec.suggested_units ?? rec.recommended_units);
  if (units === null) {
    const rawKelly = Number(rec.kelly ?? rec.kelly_fraction);
    if (Number.isFinite(rawKelly) && rawKelly > 0) {
      const kPct = rawKelly <= 1 ? rawKelly * 100 : rawKelly;
      units = Math.min(2.0, Math.max(0.5, Math.round(kPct * 4) / 4));
    } else {
      const conf = getConfidenceMeta(rec);
      units = conf.tier === 'HIGH' ? 1.5 : conf.tier === 'LOW' ? 0.5 : 1.0;
    }
  }
  const pctBankroll = parsePos(rec.bankroll_pct) ?? Number(units.toFixed(2));
  const unitsStr = Number.isInteger(units) ? `${units}u` : `${Number(units.toFixed(2))}u`;
  const pctStr = Number.isInteger(pctBankroll) ? `${pctBankroll}%` : `${Number(pctBankroll.toFixed(1))}%`;
  const br = parsePos(bankroll);
  const dollarStake = br ? Math.max(1, Math.round((pctBankroll / 100) * br)) : null;
  const tierLabel =
    rec.sizing_tier ||
    (units >= 1.5
      ? 'Strong Play'
      : units >= 1.0
        ? 'Standard Play'
        : units >= 0.4
          ? 'Half-Unit Play'
          : 'Quarter-Unit Play');

  return {
    units,
    unitsLabel: unitsStr,
    bankrollPct: pctBankroll,
    pctLabel: pctStr,
    dollarStake,
    tierLabel,
    summary: dollarStake != null ? `${unitsStr} ($${dollarStake})` : `${unitsStr} · ${pctStr} bankroll`,
    detailedLabel:
      dollarStake != null ? `${unitsStr} · ${pctStr} ($${dollarStake})` : `${unitsStr} · ${pctStr} of bankroll`,
  };
};

const TIMING_UNCERTAIN_STATUS_RE = /\b(questionable|doubtful|gtd|game[- ]time|day[- ]to[- ]day)\b/i;

const TIMING_ACTION_META = {
  BET_NOW: {
    label: 'Bet Now',
    short_label: 'Bet Now',
    tone: 'emerald',
  },
  WAIT_LINEUPS: {
    label: 'Wait · Check Lineups',
    short_label: 'Wait Lineups',
    tone: 'amber',
  },
  MONITOR: {
    label: 'Monitor · May Improve',
    short_label: 'Monitor',
    tone: 'blue',
  },
};

const extractUncertainTimingPlayers = (signals) => {
  if (!signals || typeof signals !== 'object') return [];
  const seen = new Set();
  const out = [];
  const check = (entry) => {
    if (!entry || typeof entry !== 'object') return;
    const st = String(entry.status || '').trim();
    if (!st || !TIMING_UNCERTAIN_STATUS_RE.test(st)) return;
    const label = String(entry.player || entry.name || '').trim() || 'Key player';
    const key = label.toLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      out.push(label);
    }
  };
  if (Array.isArray(signals.injuries)) {
    signals.injuries.forEach(check);
  }
  if (Array.isArray(signals.injuries_impact?.impact_players)) {
    signals.injuries_impact.impact_players.forEach(check);
  }
  return out;
};

/**
 * Compute pre-game "When to Bet" timing guidance ('BET_NOW' | 'WAIT_LINEUPS' | 'MONITOR').
 * Matches backend rules in src/utils/bet_timing.py while re-evaluating clock urgency against nowMs.
 */
export const getBetTimingGuidance = (rec, game = null, context = null, nowMs = Date.now()) => {
  if (!rec || typeof rec !== 'object') return null;

  if (game) {
    const flags = resolveLiveFlags(game);
    if (flags.isLive || flags.isFinal || flags.isHalftime) return null;
  }

  const rawStart = game?.start_time || rec?.start_time || context?.start_time;
  let minutesToTip = null;
  if (rawStart) {
    const startMs = new Date(rawStart).getTime();
    if (Number.isFinite(startMs)) {
      minutesToTip = Math.round(((startMs - nowMs) / 60000) * 10) / 10;
      if (minutesToTip <= 0) return null;
    }
  }

  const backendTiming = rec?.bet_timing;
  const backendAction = String(backendTiming?.action || '').trim().toUpperCase();
  if (
    backendTiming &&
    typeof backendTiming === 'object' &&
    TIMING_ACTION_META[backendAction] &&
    backendTiming.label &&
    backendTiming.reason
  ) {
    const tipImminentNow = minutesToTip !== null && minutesToTip <= 60;
    if (!tipImminentNow || backendAction === 'BET_NOW') {
      const meta = TIMING_ACTION_META[backendAction];
      return {
        action: backendAction,
        label: backendTiming.label || meta.label,
        short_label: backendTiming.short_label || meta.short_label,
        tone: backendTiming.tone || meta.tone,
        reason: backendTiming.reason,
        drivers: Array.isArray(backendTiming.drivers) ? backendTiming.drivers : [],
        minutes_to_tip: minutesToTip ?? toNum(backendTiming.minutes_to_tip),
      };
    }
  }

  const rawTags = rec.movement_tags || rec.sanity_reasons;
  const tags = (
    Array.isArray(rawTags)
      ? rawTags
      : typeof rawTags === 'string'
        ? rawTags.split(',')
        : []
  )
    .map((t) => String(t || '').trim().toLowerCase())
    .filter(Boolean);

  const signals = rec.signals && typeof rec.signals === 'object' ? rec.signals : {};
  const sharpEdgePts = toNum(rec.sharp_edge_pts);
  const hasSharpPriceEdge =
    (sharpEdgePts !== null && sharpEdgePts >= 0.5) ||
    tags.includes('sharp_price_edge') ||
    tags.includes('lagging_book_edge');
  const hasSharpSteam = tags.includes('rlm_confirmed') || tags.includes('sharp_backing');

  const betType = String(rec.bet_type || rec.market_type || rec.market || '').trim().toUpperCase();
  const selectionText = String(rec.selection || rec.pick || '');
  const isFirstHalf = betType === 'TOTAL_1H' || betType === 'SPREAD_1H' || tags.includes('first_half_market');
  const isSmartRisk =
    Boolean(rec.is_smart_risk) ||
    String(rec.risk_tier || '').trim().toUpperCase() === 'SMART_RISK' ||
    tags.includes('smart_risk_high_return');
  const bookName = String(rec.book || 'Sportsbook').trim() || 'Sportsbook';
  const uncertainPlayers = extractUncertainTimingPlayers(signals);

  const pack = (action, reason, drivers) => ({
    action,
    ...TIMING_ACTION_META[action],
    reason,
    drivers,
    minutes_to_tip: minutesToTip,
  });

  // 1. Tipoff imminent (<= 60 min)
  if (minutesToTip !== null && minutesToTip <= 60) {
    const drivers = ['tipoff_imminent'];
    if (hasSharpPriceEdge) drivers.push('sharp_price_edge');
    const minsInt = Math.max(1, Math.round(minutesToTip));
    if (sharpEdgePts !== null && sharpEdgePts >= 0.5) {
      return pack(
        'BET_NOW',
        `Tipoff in ~${minsInt} min and ${bookName} is ${sharpEdgePts.toFixed(1)} pts better than sharp books — lock in before close.`,
        drivers
      );
    }
    if (uncertainPlayers.length > 0) {
      return pack(
        'BET_NOW',
        `Tipoff in ~${minsInt} min — confirm final status on ${uncertainPlayers.slice(0, 2).join(', ')}, then lock in before tip.`,
        drivers
      );
    }
    return pack(
      'BET_NOW',
      `Tipoff in ~${minsInt} min — closing lines are firming up, good time to lock it in.`,
      drivers
    );
  }

  // 2. Uncertain lineup news (> 60 min or unknown start_time)
  if (uncertainPlayers.length > 0) {
    const listed = uncertainPlayers.slice(0, 2).join(', ');
    const suffix = uncertainPlayers.length > 1 ? ' listed Questionable/Doubtful' : ' is Questionable/Doubtful';
    return pack('WAIT_LINEUPS', `${listed}${suffix} — wait for lineup news ~45 min before tip.`, ['uncertain_injury']);
  }

  // 3. Sharp-book lag or sharp steam
  if (hasSharpPriceEdge || hasSharpSteam) {
    const drivers = [];
    if (hasSharpPriceEdge) {
      if ((sharpEdgePts !== null && sharpEdgePts >= 0.5) || tags.includes('sharp_price_edge')) {
        drivers.push('sharp_price_edge');
      }
      if (tags.includes('lagging_book_edge')) drivers.push('lagging_book_edge');
    }
    if (tags.includes('rlm_confirmed')) drivers.push('rlm_confirmed');
    if (tags.includes('sharp_backing')) drivers.push('sharp_backing');

    let reason = 'Big money is backing this side and the number may tighten closer to tip.';
    if (sharpEdgePts !== null && sharpEdgePts >= 0.5) {
      reason = `${bookName} is ${sharpEdgePts.toFixed(1)} pts better than sharp books — likely to move soon.`;
    } else if (tags.includes('sharp_price_edge') || tags.includes('lagging_book_edge')) {
      reason = `${bookName} is offering a better number than sharp books — take it before it adjusts.`;
    } else if (tags.includes('rlm_confirmed')) {
      reason = 'Respected money already pushed the line toward this pick — better to grab it now.';
    }
    return pack('BET_NOW', reason, drivers);
  }

  // Resolve public ticket splits
  const splitMkt =
    betType.includes('TOTAL') || /\b(OVER|UNDER)\b/i.test(selectionText)
      ? 'TOTAL'
      : betType === 'ML' || betType === 'MONEYLINE' || betType === 'H2H' || betType.includes('MONEYLINE')
        ? 'ML'
        : betType.includes('SPREAD')
          ? 'SPREAD'
          : betType;

  let pickSide = null;
  const rawSide = String(rec.side || '').trim().toUpperCase();
  if (splitMkt === 'TOTAL') {
    if (rawSide === 'OVER' || rawSide === 'UNDER') pickSide = rawSide;
    else if (/\bOVER\b/i.test(selectionText)) pickSide = 'OVER';
    else if (/\bUNDER\b/i.test(selectionText)) pickSide = 'UNDER';
  } else if (rawSide === 'HOME' || rawSide === 'AWAY') {
    pickSide = rawSide;
  } else {
    const selLow = selectionText.trim().toLowerCase();
    const hLow = String(game?.home_team || rec.home_team || context?.home_team || '').trim().toLowerCase();
    const aLow = String(game?.away_team || rec.away_team || context?.away_team || '').trim().toLowerCase();
    if (hLow && selLow.startsWith(hLow)) pickSide = 'HOME';
    else if (aLow && selLow.startsWith(aLow)) pickSide = 'AWAY';
    else if (hLow && selLow.includes(hLow) && (!aLow || !selLow.includes(aLow))) pickSide = 'HOME';
    else if (aLow && selLow.includes(aLow) && (!hLow || !selLow.includes(hLow))) pickSide = 'AWAY';
  }

  let pickBetPct = null;
  let oppBetPct = null;
  const splits = signals.public_splits;
  if (splits && typeof splits === 'object' && splitMkt && splits[splitMkt] && pickSide) {
    const oppSide =
      splitMkt === 'TOTAL' ? (pickSide === 'OVER' ? 'UNDER' : 'OVER') : pickSide === 'HOME' ? 'AWAY' : 'HOME';
    pickBetPct = toNum(splits[splitMkt][pickSide]?.bet_pct);
    oppBetPct = toNum(splits[splitMkt][oppSide]?.bet_pct);
  }

  // 4. Opposite public ticket wave
  if (oppBetPct !== null && oppBetPct >= 62.0 && (minutesToTip === null || minutesToTip > 90)) {
    return pack(
      'MONITOR',
      `${Math.round(oppBetPct)}% of public tickets are on the other side — waiting may get a better number.`,
      ['opposite_public_tickets']
    );
  }

  // 5. Early 1H or Smart Risk play (> 3h to tip)
  if ((isFirstHalf || isSmartRisk) && minutesToTip !== null && minutesToTip > 180) {
    const hrs = Math.max(1, Math.round(minutesToTip / 60));
    if (isFirstHalf) {
      return pack(
        'MONITOR',
        `1st-half limits are light with ~${hrs}h to tip — check again closer to game time.`,
        ['early_1h_market']
      );
    }
    return pack(
      'MONITOR',
      `Higher-variance Smart Risk play with ~${hrs}h to tip — monitor line moves before sizing in.`,
      ['early_smart_risk']
    );
  }

  // 6. Our-side public steam or high conviction
  const adj = signals.adjustments && typeof signals.adjustments === 'object' ? signals.adjustments : {};
  const rawAgree = betType.includes('TOTAL')
    ? rec.conviction_sources_total ?? adj.conviction_sources_total ?? context?.conviction_sources_total
    : rec.conviction_sources ?? adj.conviction_sources ?? context?.conviction_sources;
  const agreeCount = Math.round(toNum(rawAgree) ?? 0);
  const evDec = getRecEv(rec);

  const hasOurPublic = pickBetPct !== null && pickBetPct >= 65.0;
  const hasHighConv = agreeCount >= 3;
  const hasStrongEv = evDec !== null && evDec >= 0.06;
  if (hasOurPublic || hasHighConv || hasStrongEv) {
    const drivers = [];
    if (hasOurPublic) drivers.push('our_public_steam');
    if (hasHighConv) drivers.push('high_conviction');
    if (hasStrongEv) drivers.push('strong_ev');

    let reason = `High +${(evDec * 100).toFixed(1)}% value cushion is likely to trim down closer to tipoff.`;
    if (hasOurPublic) {
      reason = `${Math.round(pickBetPct)}% of tickets are backing this side — bet now before the line moves away.`;
    } else if (hasHighConv) {
      reason = `${agreeCount}-of-${agreeCount} rating models agree with no injury flags — strong number to grab now.`;
    }
    return pack('BET_NOW', reason, drivers);
  }

  // 7. Default fallback
  if (minutesToTip !== null && minutesToTip > 240) {
    const hrs = Math.max(1, Math.round(minutesToTip / 60));
    return pack(
      'MONITOR',
      `No sharp-book rush yet with ~${hrs}h to tip — fine to watch for a better number.`,
      ['early_no_rush']
    );
  }

  return pack('BET_NOW', 'Clean number with no lineup flags — good to lock in now.', ['clean_number']);
};

const TIMING_SHARP_URGENCY_DRIVERS = new Set([
  'sharp_price_edge',
  'lagging_book_edge',
  'rlm_confirmed',
  'sharp_backing',
]);
const TIMING_SIGNAL_URGENCY_DRIVERS = new Set([
  'our_public_steam',
  'high_conviction',
  'strong_ev',
]);
const DECIDED_PARLAY_OUTCOMES = new Set(['WON', 'LOST', 'PUSH', 'VOID', 'WON (PARTIAL)']);

const parlayLegLabel = (leg) =>
  String(leg?.team_pick || leg?.selection || leg?.pick || 'Leg').trim() || 'Leg';

/**
 * Resolve pre-game "When to Bet" guidance for a multi-leg parlay, honoring backend
 * timing while auto-escalating imminent tips and returning null once started/decided.
 */
export const getParlayTimingGuidance = (parlay, nowMs = Date.now()) => {
  if (!parlay || typeof parlay !== 'object') return null;

  const rawOutcome = String(parlay.outcome || '').trim().toUpperCase();
  if (DECIDED_PARLAY_OUTCOMES.has(rawOutcome)) return null;

  const legs = Array.isArray(parlay.legs) ? parlay.legs : [];
  let earliestMins = null;
  for (const leg of legs) {
    if (leg?.start_time) {
      const startMs = new Date(leg.start_time).getTime();
      if (Number.isFinite(startMs)) {
        const mins = Math.round(((startMs - nowMs) / 60000) * 10) / 10;
        if (mins <= 0) return null;
        earliestMins = earliestMins === null ? mins : Math.min(earliestMins, mins);
      }
    }
  }

  const backendTiming = parlay.bet_timing;
  const backendAction = String(backendTiming?.action || '').trim().toUpperCase();
  if (
    backendTiming &&
    typeof backendTiming === 'object' &&
    TIMING_ACTION_META[backendAction] &&
    backendTiming.label &&
    backendTiming.reason
  ) {
    const tipImminentNow = earliestMins !== null && earliestMins <= 60;
    if (!tipImminentNow || backendAction === 'BET_NOW') {
      const meta = TIMING_ACTION_META[backendAction];
      return {
        action: backendAction,
        label: backendTiming.label || meta.label,
        short_label: backendTiming.short_label || meta.short_label,
        tone: backendTiming.tone || meta.tone,
        reason: backendTiming.reason,
        drivers: Array.isArray(backendTiming.drivers) ? backendTiming.drivers : [],
        minutes_to_tip: earliestMins ?? toNum(backendTiming.minutes_to_tip),
        leg_actions: Array.isArray(backendTiming.leg_actions) ? backendTiming.leg_actions : undefined,
      };
    }
    const minsInt = Math.max(1, Math.round(earliestMins));
    return {
      action: 'BET_NOW',
      label: TIMING_ACTION_META.BET_NOW.label,
      short_label: TIMING_ACTION_META.BET_NOW.short_label,
      tone: TIMING_ACTION_META.BET_NOW.tone,
      reason: `Earliest leg tips in ~${minsInt} min — lock in before tip.`,
      drivers: ['tipoff_imminent'],
      minutes_to_tip: earliestMins,
    };
  }

  if (legs.length === 0) return null;

  const paired = [];
  for (const leg of legs) {
    const legTiming = getBetTimingGuidance(
      leg,
      {
        start_time: leg?.start_time,
        home_team: leg?.home_team,
        away_team: leg?.away_team,
        status: 'SCHEDULED',
      },
      null,
      nowMs
    );
    if (!legTiming) return null;
    paired.push({ leg, timing: legTiming });
  }

  const allDrivers = [];
  const seenDrivers = new Set();
  for (const { timing } of paired) {
    for (const drv of timing.drivers || []) {
      const key = String(drv || '').trim();
      if (key && !seenDrivers.has(key)) {
        seenDrivers.add(key);
        allDrivers.push(key);
      }
    }
  }
  const legActions = paired.map(({ timing }) => timing.action);

  if (earliestMins !== null && earliestMins <= 60) {
    const minsInt = Math.max(1, Math.round(earliestMins));
    return {
      action: 'BET_NOW',
      label: TIMING_ACTION_META.BET_NOW.label,
      short_label: TIMING_ACTION_META.BET_NOW.short_label,
      tone: TIMING_ACTION_META.BET_NOW.tone,
      reason: `Earliest leg tips in ~${minsInt} min — lock in before tip.`,
      drivers: ['tipoff_imminent', ...allDrivers.filter((d) => d !== 'tipoff_imminent')],
      minutes_to_tip: earliestMins,
      leg_actions: legActions,
    };
  }

  const waitPair = paired.find(({ timing }) => timing.action === 'WAIT_LINEUPS');
  if (waitPair) {
    return {
      action: 'WAIT_LINEUPS',
      label: TIMING_ACTION_META.WAIT_LINEUPS.label,
      short_label: TIMING_ACTION_META.WAIT_LINEUPS.short_label,
      tone: TIMING_ACTION_META.WAIT_LINEUPS.tone,
      reason: `${parlayLegLabel(waitPair.leg)}: ${waitPair.timing.reason}`,
      drivers: allDrivers,
      minutes_to_tip: earliestMins,
      leg_actions: legActions,
    };
  }

  const betNowPairs = paired
    .map((entry, idx) => ({ ...entry, idx }))
    .filter(({ timing }) => timing.action === 'BET_NOW');
  if (betNowPairs.length > 0) {
    const rankUrgency = ({ timing, idx }) => {
      const drvs = timing.drivers || [];
      if (drvs.some((d) => TIMING_SHARP_URGENCY_DRIVERS.has(d))) return [0, idx];
      if (drvs.some((d) => TIMING_SIGNAL_URGENCY_DRIVERS.has(d))) return [1, idx];
      return [2, idx];
    };
    betNowPairs.sort((a, b) => {
      const ra = rankUrgency(a);
      const rb = rankUrgency(b);
      return ra[0] - rb[0] || ra[1] - rb[1];
    });
    const topPair = betNowPairs[0];
    return {
      action: 'BET_NOW',
      label: TIMING_ACTION_META.BET_NOW.label,
      short_label: TIMING_ACTION_META.BET_NOW.short_label,
      tone: TIMING_ACTION_META.BET_NOW.tone,
      reason: `${parlayLegLabel(topPair.leg)}: ${topPair.timing.reason}`,
      drivers: allDrivers,
      minutes_to_tip: earliestMins,
      leg_actions: legActions,
    };
  }

  const monPair = [...paired].sort((a, b) => {
    const am = toNum(a.timing.minutes_to_tip);
    const bm = toNum(b.timing.minutes_to_tip);
    return (am ?? Infinity) - (bm ?? Infinity);
  })[0];
  return {
    action: 'MONITOR',
    label: TIMING_ACTION_META.MONITOR.label,
    short_label: TIMING_ACTION_META.MONITOR.short_label,
    tone: TIMING_ACTION_META.MONITOR.tone,
    reason: `${parlayLegLabel(monPair.leg)}: ${monPair.timing.reason}`,
    drivers: allDrivers,
    minutes_to_tip: earliestMins,
    leg_actions: legActions,
  };
};

const OUTCOME_SURFACE_MAP = {
  bet: {
    WON: {
      borderCls: 'border-2 border-emerald-500/80 hover:border-emerald-400',
      tintCls: 'bg-gradient-to-br from-emerald-950/75 via-emerald-950/40 to-slate-950 shadow-[0_0_24px_rgba(16,185,129,0.20)]',
      rowCls: 'bg-emerald-950/40 hover:bg-emerald-950/55',
      stripeCls: 'border-l-4 border-l-emerald-400',
      badgeCls: 'bg-emerald-500/25 border-emerald-400/60 text-emerald-200',
    },
    LOST: {
      borderCls: 'border-2 border-rose-500/80 hover:border-rose-400',
      tintCls: 'bg-gradient-to-br from-rose-950/75 via-rose-950/40 to-slate-950 shadow-[0_0_24px_rgba(244,63,94,0.20)]',
      rowCls: 'bg-rose-950/40 hover:bg-rose-950/55',
      stripeCls: 'border-l-4 border-l-rose-400',
      badgeCls: 'bg-rose-500/25 border-rose-400/60 text-rose-200',
    },
    PUSH: {
      borderCls: 'border-2 border-slate-500/75 hover:border-slate-400',
      tintCls: 'bg-gradient-to-br from-slate-800/75 via-slate-900 to-slate-950',
      rowCls: 'bg-slate-800/55 hover:bg-slate-800/70',
      stripeCls: 'border-l-4 border-l-slate-400',
      badgeCls: 'bg-slate-700/80 border-slate-500 text-slate-200',
    },
    DEFAULT: {
      borderCls: 'border border-slate-700/80 hover:border-indigo-500/40',
      tintCls: 'bg-gradient-to-br from-slate-900 via-slate-900/95 to-slate-950',
      rowCls: 'hover:bg-slate-800/40',
      stripeCls: '',
      badgeCls: 'bg-slate-800 border-slate-700 text-slate-300',
    },
  },
  lean: {
    WON: {
      borderCls: 'border-2 border-dashed border-emerald-400/75 hover:border-emerald-300',
      tintCls: 'bg-gradient-to-br from-emerald-950/45 via-emerald-950/20 to-slate-950 shadow-[0_0_18px_rgba(16,185,129,0.14)]',
      rowCls: 'bg-emerald-950/20 hover:bg-emerald-950/30',
      stripeCls: 'border-l-2 border-dashed border-l-emerald-400/70',
      badgeCls: 'bg-emerald-500/15 border-dashed border-emerald-400/60 text-emerald-200',
    },
    LOST: {
      borderCls: 'border-2 border-dashed border-rose-400/75 hover:border-rose-300',
      tintCls: 'bg-gradient-to-br from-rose-950/45 via-rose-950/20 to-slate-950 shadow-[0_0_18px_rgba(244,63,94,0.14)]',
      rowCls: 'bg-rose-950/20 hover:bg-rose-950/30',
      stripeCls: 'border-l-2 border-dashed border-l-rose-400/70',
      badgeCls: 'bg-rose-500/15 border-dashed border-rose-400/60 text-rose-200',
    },
    PUSH: {
      borderCls: 'border-2 border-dashed border-slate-400/70 hover:border-slate-300',
      tintCls: 'bg-gradient-to-br from-slate-800/55 via-slate-900 to-slate-950',
      rowCls: 'bg-slate-800/35 hover:bg-slate-800/50',
      stripeCls: 'border-l-2 border-dashed border-l-slate-400/60',
      badgeCls: 'bg-slate-800/80 border-dashed border-slate-500/60 text-slate-200',
    },
    DEFAULT: {
      borderCls: 'border border-slate-800 hover:border-indigo-500/40',
      tintCls: 'bg-slate-900/75',
      rowCls: 'hover:bg-slate-800/40',
      stripeCls: '',
      badgeCls: 'bg-indigo-500/15 border-indigo-400/30 text-indigo-200',
    },
  },
};

/**
 * Shared settled-outcome border/background/stripe/badge styling across cards, tables, parlays, and ledgers.
 */
export const getOutcomeOutlineClasses = (rawVerdict, variant = 'bet') => {
  const s = String(rawVerdict || '').trim().toUpperCase();
  const outcome =
    s === 'WON' || s === 'WIN' || s === 'WON (PARTIAL)'
      ? 'WON'
      : s === 'LOST' || s === 'LOSE' || s === 'LOSS'
        ? 'LOST'
        : s === 'PUSH'
          ? 'PUSH'
          : null;
  const group = OUTCOME_SURFACE_MAP[variant === 'lean' ? 'lean' : 'bet'];
  const entry = (outcome && group[outcome]) || group.DEFAULT;
  return {
    outcome,
    cardCls: `${entry.borderCls} ${entry.tintCls}`,
    borderCls: entry.borderCls,
    rowCls: entry.rowCls,
    stripeCls: entry.stripeCls,
    badgeCls: entry.badgeCls,
  };
};

/**
 * Determine whether an Axios/fetch error is transient and safe to retry once.
 */
export const isRetryableRequestError = (err, signal = null) => {
  if (
    signal?.aborted ||
    err?.code === 'ERR_CANCELED' ||
    err?.name === 'CanceledError' ||
    err?.name === 'AbortError'
  ) {
    return false;
  }
  const status = err?.response?.status;
  if (typeof status === 'number') {
    return status === 408 || status === 429 || status >= 500;
  }
  return true;
};

const sleepWithAbort = (ms, signal) =>
  new Promise((resolve, reject) => {
    if (signal?.aborted) {
      const abortErr = new Error('Request aborted');
      abortErr.name = 'AbortError';
      abortErr.code = 'ERR_CANCELED';
      reject(abortErr);
      return;
    }
    let settled = false;
    const onAbort = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      const abortErr = new Error('Request aborted');
      abortErr.name = 'AbortError';
      abortErr.code = 'ERR_CANCELED';
      reject(abortErr);
    };
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      signal?.removeEventListener?.('abort', onAbort);
      resolve();
    }, ms);
    signal?.addEventListener?.('abort', onAbort, { once: true });
  });

/**
 * Execute an async request with bounded retry on transient network/5xx/timeout errors.
 */
export async function fetchWithRetry(requestFn, { retries = 1, delayMs = 600, signal = null } = {}) {
  let attempt = 0;
  while (true) {
    try {
      return await requestFn();
    } catch (err) {
      if (attempt >= retries || !isRetryableRequestError(err, signal)) {
        throw err;
      }
      attempt += 1;
      if (delayMs > 0) {
        await sleepWithAbort(delayMs, signal);
      }
    }
  }
}

/**
 * Normalize a /api/ncaam/top-picks payload map into event-ID and matchup-key lookups.
 */
export function mapTopPicksPayload(picksObj) {
  const mapped = {};
  const mappedByKey = {};
  if (!picksObj || typeof picksObj !== 'object') {
    return { mapped, mappedByKey };
  }
  Object.keys(picksObj).forEach((eid) => {
    const item = picksObj[eid];
    const recObj = {
      rec: item?.rec,
      analyzedAt: item?.analyzed_at,
      isActionable: item?.is_actionable,
      reason: item?.reason,
      source: item?.source,
      event: item?.event,
      context: item?.context || null,
      model_version: item?.model_version || null,
    };
    mapped[eid] = recObj;
    const ev = item?.event || {};
    const k = makeMatchupKey(String(ev.day_et || '').slice(0, 10), ev.away_team, ev.home_team);
    if (k && !mappedByKey[k]) mappedByKey[k] = recObj;
  });
  return { mapped, mappedByKey };
}
