export const determineMatchFavorite = (match) => {
    if (!match) return null;
    const winA = Number(match.win_prob_a) || 0;
    const winB = Number(match.win_prob_b) || 0;
    if (winA >= winB) {
        return {
            favoriteTeam: match.team_a,
            favoritePct: winA,
            dogPct: winB
        };
    }
    return {
        favoriteTeam: match.team_b,
        favoritePct: winB,
        dogPct: winA
    };
};
