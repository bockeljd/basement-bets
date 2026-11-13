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

export const getConfidenceMeta = (rec) => {
  if (!rec) return { tier: 'LOW', score: null, badgeCls: 'bg-slate-800 text-slate-300 border-slate-700' };
  const tier = String(rec.confidence_tier || '').toUpperCase();
  const rawScore = Number(rec.confidence_0_100 ?? rec.confidence);
  const score = Number.isFinite(rawScore) ? Math.round(rawScore <= 1 ? rawScore * 100 : rawScore) : null;
  const resolved = tier || (score >= 80 ? 'HIGH' : score >= 50 ? 'MEDIUM' : 'LOW');
  if (resolved === 'HIGH') {
    return {
      tier: 'HIGH',
      score,
      badgeCls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/35',
    };
  }
  if (resolved === 'MEDIUM') {
    return {
      tier: 'MEDIUM',
      score,
      badgeCls: 'bg-amber-500/15 text-amber-300 border-amber-500/35',
    };
  }
  return {
    tier: 'LOW',
    score,
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
      alert('Open kenpom.com while logged in so the ratings table is visible, then click this bookmark again.');
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
    var w=window.open(${destPrefix}+encodeURIComponent(b64),'_blank');
    try{if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(tsv).catch(function(){});}}catch(e){}
    if(!w){
      alert('Pop-up was blocked — your KenPom table was copied to clipboard instead. Paste it under Option 2 in Enable KenPom.');
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
