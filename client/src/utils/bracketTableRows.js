import { determineMatchFavorite } from './bracketTableUtils.js';

const STATUS_FINAL = 'final';

export const resolveBracketFavorite = (match) => {
    const favoriteRow = determineMatchFavorite(match);
    let favoriteTeam = favoriteRow.favoriteTeam;
    let favoritePct = favoriteRow.favoritePct;
    let dogPct = favoriteRow.dogPct;

    if (match.status === STATUS_FINAL && match.display_winner) {
        const actualWinner = match.display_winner;
        const actualPct = actualWinner === match.team_a ? Number(match.win_prob_a) || 0 : Number(match.win_prob_b) || 0;
        const opponentPct = actualWinner === match.team_a ? Number(match.win_prob_b) || 0 : Number(match.win_prob_a) || 0;
        favoriteTeam = actualWinner;
        favoritePct = actualPct;
        dogPct = opponentPct;
    }

    return { favoriteTeam, favoritePct, dogPct };
};
