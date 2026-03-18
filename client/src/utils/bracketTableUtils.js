export function determineMatchFavorite(match) {
    if (!match) return null;
    const winProbA = Number(match.win_prob_a) || 0;
    const winProbB = Number(match.win_prob_b) || 0;
    if (winProbA >= winProbB) {
        return {
            favoriteTeam: match.team_a,
            favoritePct: winProbA,
            dogPct: winProbB
        };
    }
    return {
        favoriteTeam: match.team_b,
        favoritePct: winProbB,
        dogPct: winProbA
    };
}
