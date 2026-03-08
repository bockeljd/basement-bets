const axios = require('axios');
require('dotenv').config({path: 'client/.env.local'});
const pwd = process.env.VITE_BASEMENT_PASSWORD;

async function run() {
    try {
        const res = await axios.get('https://basement-bets.vercel.app/api/ncaam/parlays/today?strategy=home_fav&parlay_odds_lo=-200&parlay_odds_hi=120', {
            headers: { 'X-BASEMENT-KEY': pwd }
        });
        console.log("HOME FAVS");
        const hf = res.data.high_confidence || [];
        hf.slice(0, 3).forEach(c => {
            console.log(c.american_odds, c.legs.map(l => l.team_pick).join(' + '));
        });

        const res2 = await axios.get('https://basement-bets.vercel.app/api/ncaam/parlays/today', {
            headers: { 'X-BASEMENT-KEY': pwd }
        });
        console.log("\nALL");
        const hf2 = res2.data.high_confidence || [];
        hf2.slice(0, 3).forEach(c => {
            console.log(c.american_odds, c.legs.map(l => l.team_pick).join(' + '));
        });
        const hf3 = res2.data.payout_band || [];
        console.log("\nALL PAYOUT");
        hf3.slice(0, 3).forEach(c => {
            console.log(c.american_odds, c.legs.map(l => l.team_pick).join(' + '));
        });
    } catch (e) {
        console.error(e.response ? e.response.statusText : e.message);
    }
}
run();
