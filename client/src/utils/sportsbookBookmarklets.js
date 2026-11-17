/**
 * Chrome bookmarklets (`javascript:...`) for 1-click DraftKings & FanDuel sync.
 * Uses the exact hash transfer pattern (#sb_import=...) used by KenPom sync so
 * strict sportsbook CSP connect-src rules never block sending slips to Basement Bets.
 */

const encodeUtf8PayloadJs = `
  var bytes = new TextEncoder().encode(payload);
  var bin = '';
  for (var i = 0; i < bytes.length; i += 8192) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
  }
  var dest = destPrefix + encodeURIComponent(btoa(bin));
  var w = window.open(dest, '_blank');
  if (!w) { window.location.href = dest; }
`;

/**
 * Build a 1-click Chrome bookmarklet for FanDuel (`sportsbook.fanduel.com`).
 * Tries same-origin / sbapi fetch first using active login/token, then falls back to
 * reading rendered Open/Settled cards & balance directly from the page DOM.
 */
export const buildFanDuelBookmarklet = (appOrigin, accountId = 'Main') => {
  const cleanOrigin = String(appOrigin || '').replace(/\/+$/, '');
  const destPrefix = JSON.stringify(`${cleanOrigin}/#sb_import=`);
  const safeAcc = JSON.stringify(accountId === 'User2' ? 'User2' : 'Main');

  const body = `(function(){
    var destPrefix=${destPrefix};
    var accId=${safeAcc};
    if(location.hostname.indexOf('fanduel.com')===-1){
      if(confirm('You are not on FanDuel yet.\\n\\nClick OK to open FanDuel My Bets in a new tab. Once logged in, click this bookmark again to sync Open & Settled bets.')){
        window.open('https://sportsbook.fanduel.com/my-bets','_blank');
      }
      return;
    }
    var old=document.getElementById('bb-sb-sync');
    if(old&&old.parentNode){old.parentNode.removeChild(old);}
    var pill=document.createElement('div');
    pill.id='bb-sb-sync';
    pill.style.cssText='position:fixed;top:16px;right:16px;z-index:2147483647;background:#0f172a;color:#6ee7b7;border:1px solid #10b981;padding:12px 16px;border-radius:10px;font:600 13px/1.4 system-ui,sans-serif;box-shadow:0 10px 25px rgba(0,0,0,0.45);';
    pill.textContent='Basement Bets: Reading FanDuel open & settled bets...';
    if(document.body){document.body.appendChild(pill);}
    function findToken(){
      try{
        var stores=[localStorage,sessionStorage];
        for(var s=0;s<stores.length;s++){
          for(var i=0;i<stores[s].length;i++){
            var v=stores[s].getItem(stores[s].key(i))||'';
            if(v.indexOf('eyJ')!==-1&&v.length<4000){
              var m=v.match(/eyJ[A-Za-z0-9_-]{20,}\\.[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]{10,}/);
              if(m)return m[0];
            }
          }
        }
      }catch(e){}
      return '';
    }
    function readBalance(){
      try{
        var sels=['[data-testid*="balance" i]','[data-test-id*="balance" i]','[data-testid*="wallet" i]','[class*="cash-balance" i]','[class*="wallet-balance" i]','[aria-label*="balance" i]'];
        var bad=/bonus|promo|reward|crown|dk\\s*dollar|free|boost|bet\\s*\\$|get\\s*\\$/i;
        for(var i=0;i<sels.length;i++){
          var els=document.querySelectorAll(sels[i]);
          for(var j=0;j<els.length;j++){
            var txt=(els[j].innerText||'').trim();
            if(!txt||txt.length>80||bad.test(txt))continue;
            var m=txt.match(/\\$([0-9,]+\\.\\d{2})/);
            if(m){return parseFloat(m[1].replace(/,/g,''));}
          }
        }
      }catch(e){}
      return null;
    }
    var tok=findToken();
    var hostMatch=location.hostname.match(/^([a-z0-9-]+)\\.sportsbook\\.fanduel\\.com/i);
    var region=(hostMatch&&hostMatch[1]&&hostMatch[1]!=='sportsbook')?hostMatch[1]:'il';
    var headers={'X-Application':'FhMFpcPWXMeyZxOx','Accept':'application/json'};
    if(tok){headers['X-Auth-Token']=tok;}
    function fetchFd(settled){
      var u='https://sbapi.'+region+'.sportsbook.fanduel.com/api/mybets/v1/getBetHistory?isSettled='+(settled?'true':'false')+'&fromRecord=1&toRecord='+(settled?100:50)+'&sortDir=DESC&sortParam='+(settled?'SETTLEMENT_DATE':'PLACED_DATE')+'&adaptiveTokenEnabled=false&_ak=FhMFpcPWXMeyZxOx';
      return fetch(u,{credentials:'include',headers:headers}).then(function(r){return r.ok?r.json():null;}).catch(function(){return null;});
    }
    Promise.all([fetchFd(false),fetchFd(true)]).then(function(res){
      var rawText=(document.querySelector('main')||document.body).innerText||'';
      var bal=readBalance();
      var rawBets=[];
      res.forEach(function(r){if(r&&Array.isArray(r.bets)){rawBets=rawBets.concat(r.bets);}});
      var apiBets=rawBets.map(function(b){
        var legs=b.legs||[];
        var desc=[];var evs=[];var sport='Unknown';var odds=null;var isLive=!!(b.isInPlay||b.inPlay);
        legs.forEach(function(l){(l.parts||[]).forEach(function(p){
          if(p.selectionName){desc.push(p.selectionName+(p.eventMarketDescription?' ('+p.eventMarketDescription+')':''));}
          if(p.eventDescription&&evs.indexOf(p.eventDescription)===-1){evs.push(p.eventDescription);}
          if(p.competitionName){sport=p.competitionName;}
          if(odds===null&&p.americanPrice!==undefined){odds=p.americanPrice;}
        });});
        var stake=parseFloat(b.currentSize||b.betPrice||b.stake||0)||0;
        var payout=parseFloat(b.payout||b.settledPayout||b.paid||0)||0;
        var st=b.isSettled===false?'PENDING':(b.settledResult||'PENDING');
        if(st==='LOSS'){payout=0;}
        return {
          provider:'FanDuel',account_id:accId,external_id:b.betId||b.id||null,
          placed_at:b.placedDate||b.settledDate||'',sport:sport,
          bet_type:b.betType||'Straight',wager:stake,payout:payout,
          profit:(st==='PENDING')?0:(payout-stake),status:st,
          description:evs.join(' / ')||desc.join(' | '),selection:desc.join(' | ')||evs.join(' / '),
          odds:(b.odds&&b.odds.american)||odds,is_live:isLive,is_bonus:!!(b.isBonus||b.bonusBet)
        };
      });
      if(pill.parentNode){pill.parentNode.removeChild(pill);}
      if(!apiBets.length&&rawText.indexOf('BET ID:')===-1){
        alert('No FanDuel bets detected on this page yet. Open My Bets (Open or Settled), scroll down slightly, and click this bookmark again.');
        return;
      }
      var payload=JSON.stringify({_bb_sb_bundle:1,provider:'FanDuel',account_id:accId,api_bets:apiBets,raw_text:apiBets.length?'':rawText.slice(0,180000),balance:bal,source:'fanduel_bookmarklet'});
      ${encodeUtf8PayloadJs}
    }).catch(function(err){
      if(pill.parentNode){pill.parentNode.removeChild(pill);}
      alert('FanDuel sync error: '+(err&&err.message?err.message:err));
    });
  })();`;
  return `javascript:${body.replace(/\n\s*/g, '')}`;
};

/**
 * Build a 1-click Chrome bookmarklet for DraftKings (`sportsbook.draftkings.com`).
 * Extracts visible Open/Settled slip cards + balance cleanly from the logged-in tab.
 */
export const buildDraftKingsBookmarklet = (appOrigin, accountId = 'Main') => {
  const cleanOrigin = String(appOrigin || '').replace(/\/+$/, '');
  const destPrefix = JSON.stringify(`${cleanOrigin}/#sb_import=`);
  const safeAcc = JSON.stringify(accountId === 'User2' ? 'User2' : 'Main');

  const body = `(function(){
    var destPrefix=${destPrefix};
    var accId=${safeAcc};
    if(location.hostname.indexOf('draftkings.com')===-1){
      if(confirm('You are not on DraftKings yet.\\n\\nClick OK to open DraftKings My Bets in a new tab. Once logged in, click this bookmark again to sync Open & Settled bets.')){
        window.open('https://sportsbook.draftkings.com/mybets','_blank');
      }
      return;
    }
    var old=document.getElementById('bb-sb-sync');
    if(old&&old.parentNode){old.parentNode.removeChild(old);}
    var pill=document.createElement('div');
    pill.id='bb-sb-sync';
    pill.style.cssText='position:fixed;top:16px;right:16px;z-index:2147483647;background:#0f172a;color:#6ee7b7;border:1px solid #10b981;padding:12px 16px;border-radius:10px;font:600 13px/1.4 system-ui,sans-serif;box-shadow:0 10px 25px rgba(0,0,0,0.45);';
    pill.textContent='Basement Bets: Extracting DraftKings bets & balance...';
    if(document.body){document.body.appendChild(pill);}
    function readBalance(){
      try{
        var sels=['[data-testid*="balance" i]','[data-test-id*="balance" i]','[data-testid*="wallet" i]','[class*="cash-balance" i]','[class*="wallet-balance" i]','[aria-label*="balance" i]'];
        var bad=/bonus|promo|reward|crown|dk\\s*dollar|free|boost|bet\\s*\\$|get\\s*\\$/i;
        for(var i=0;i<sels.length;i++){
          var els=document.querySelectorAll(sels[i]);
          for(var j=0;j<els.length;j++){
            var txt=(els[j].innerText||'').trim();
            if(!txt||txt.length>80||bad.test(txt))continue;
            var m=txt.match(/\\$([0-9,]+\\.\\d{2})/);
            if(m){return parseFloat(m[1].replace(/,/g,''));}
          }
        }
      }catch(e){}
      return null;
    }
    var root=document.querySelector('main')||document.body;
    var cardSels=["[data-testid*='bet-card']","[data-test-id*='bet-card']","[class*='bet-card']","[class*='BetCard']","[data-testid*='bet']","[data-test-id*='bet']"];
    var els=[];
    cardSels.forEach(function(sel){
      root.querySelectorAll(sel).forEach(function(el){
        if(els.indexOf(el)===-1){els.push(el);}
      });
    });
    var leafEls=els.filter(function(el){
      return !els.some(function(other){return other!==el&&el.contains(other);});
    });
    var seen={};var cards=[];
    (leafEls.length?leafEls:els).forEach(function(el){
      var t=(el.innerText||'').trim();
      if(!t||t.length<45||seen[t])return;
      var dkIds=t.match(/DK\\d{10,}/g)||[];
      if(dkIds.length>1)return;
      var tl=t.toLowerCase();
      var hasOutcome=/\\b(won|lost|void|push|cashed|open)\\b|to win|payout/.test(tl);
      var hasMoney=/\\$|usd/.test(tl);
      if(hasOutcome&&hasMoney){seen[t]=true;cards.push(t);}
    });
    var rawText=cards.length?cards.join('\\n\\n'):(root.innerText||'');
    var bal=readBalance();
    if(pill.parentNode){pill.parentNode.removeChild(pill);}
    if(!rawText||rawText.length<40){
      alert('No DraftKings bets detected yet. Make sure you are on My Bets (Open or Settled) and click again.');
      return;
    }
    var payload=JSON.stringify({_bb_sb_bundle:1,provider:'DraftKings',account_id:accId,raw_text:rawText.slice(0,180000),balance:bal,source:'draftkings_bookmarklet'});
    ${encodeUtf8PayloadJs}
  })();`;
  return `javascript:${body.replace(/\n\s*/g, '')}`;
};

/**
 * Decode `#sb_import=<base64>` hash payload back into JSON object.
 */
export const decodeSportsbookHashImport = (hashStr) => {
  const raw = String(hashStr || '');
  const idx = raw.indexOf('sb_import=');
  if (idx === -1) return null;
  let encoded = raw.slice(idx + 'sb_import='.length);
  const ampIdx = encoded.indexOf('&');
  if (ampIdx !== -1) encoded = encoded.slice(0, ampIdx);
  if (!encoded) return null;
  const b64 = decodeURIComponent(encoded);
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) {
    bytes[i] = bin.charCodeAt(i);
  }
  const decoded = new TextDecoder().decode(bytes);
  return JSON.parse(decoded);
};
