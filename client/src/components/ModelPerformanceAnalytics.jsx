// Model Performance Analytics Component
const ModelPerformanceAnalytics = ({ history }) => {
    const graded = history.filter(h => h.result && h.result !== 'Pending');
    const wins = graded.filter(h => h.result === 'Win').length;
    const losses = graded.filter(h => h.result === 'Loss').length;
    const pushes = graded.filter(h => h.result === 'Push').length;
    const winRate = graded.length > 0 ? (wins / (wins + losses) * 100) : 0;
    const roi = graded.length > 0 ? ((wins * 9.09 - losses * 10) / (graded.length * 10) * 100) : 0;

    // Performance by edge threshold
    const edgeThresholds = [0.5, 1.0, 2.0, 3.0, 5.0];
    const edgePerformance = edgeThresholds.map(threshold => {
        const filtered = graded.filter(h => (h.edge || 0) >= threshold);
        const w = filtered.filter(h => h.result === 'Win').length;
        const l = filtered.filter(h => h.result === 'Loss').length;
        const wr = filtered.length > 0 ? (w / (w + l) * 100) : 0;
        const r = filtered.length > 0 ? ((w * 9.09 - l * 10) / (filtered.length * 10) * 100) : 0;
        return { threshold, count: filtered.length, wins: w, losses: l, winRate: wr, roi: r };
    }).filter(e => e.count > 0);

    // Performance by sport
    const sports = [...new Set(graded.map(h => h.sport))];
    const sportPerformance = sports.map(sport => {
        const filtered = graded.filter(h => h.sport === sport);
        const w = filtered.filter(h => h.result === 'Win').length;
        const l = filtered.filter(h => h.result === 'Loss').length;
        const wr = filtered.length > 0 ? (w / (w + l) * 100) : 0;
        const r = filtered.length > 0 ? ((w * 9.09 - l * 10) / (filtered.length * 10) * 100) : 0;
        return { sport, count: filtered.length, wins: w, losses: l, winRate: wr, roi: r };
    });

    // Performance by market type
    const markets = [...new Set(graded.map(h => h.market))];
    const marketPerformance = markets.map(market => {
        const filtered = graded.filter(h => h.market === market);
        const w = filtered.filter(h => h.result === 'Win').length;
        const l = filtered.filter(h => h.result === 'Loss').length;
        const wr = filtered.length > 0 ? (w / (w + l) * 100) : 0;
        const r = filtered.length > 0 ? ((w * 9.09 - l * 10) / (filtered.length * 10) * 100) : 0;
        return { market, count: filtered.length, wins: w, losses: l, winRate: wr, roi: r };
    });

    if (graded.length === 0) return null;

    return (
        <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700 mb-6">
            <h3 className="text-lg font-bold text-white mb-4 flex items-center">
                📊 Model Performance Analytics
            </h3>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Overall Stats */}
                <div className="bg-slate-900/50 rounded-lg p-4 border border-slate-700">
                    <h4 className="text-sm font-bold text-slate-400 uppercase mb-3">Overall Performance</h4>
                    <div className="space-y-2">
                        <div className="flex justify-between">
                            <span className="text-slate-400">Record:</span>
                            <span className="text-white font-bold">{wins}-{losses}-{pushes}</span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-slate-400">Win Rate:</span>
                            <span className={`font-bold ${winRate >= 55 ? 'text-green-400' : winRate >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
                                {winRate.toFixed(1)}%
                            </span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-slate-400">ROI:</span>
                            <span className={`font-bold ${roi >= 5 ? 'text-green-400' : roi >= 0 ? 'text-yellow-400' : 'text-red-400'}`}>
                                {roi >= 0 ? '+' : ''}{roi.toFixed(1)}%
                            </span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-slate-400">Total Bets:</span>
                            <span className="text-white font-bold">{graded.length}</span>
                        </div>
                    </div>
                </div>

                {/* Performance by Edge */}
                <div className="bg-slate-900/50 rounded-lg p-4 border border-slate-700">
                    <h4 className="text-sm font-bold text-slate-400 uppercase mb-3">Performance by Edge</h4>
                    <div className="space-y-2 text-xs">
                        {edgePerformance.map(edge => (
                            <div key={edge.threshold} className="flex justify-between items-center">
                                <span className="text-slate-400">Edge ≥ {edge.threshold} pts:</span>
                                <div className="flex items-center space-x-2">
                                    <span className="text-slate-500">{edge.wins}-{edge.losses}</span>
                                    <span className={`font-bold ${edge.winRate >= 55 ? 'text-green-400' : edge.winRate >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
                                        {edge.winRate.toFixed(0)}%
                                    </span>
                                    <span className={`text-xs ${edge.roi >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                        ({edge.roi >= 0 ? '+' : ''}{edge.roi.toFixed(0)}%)
                                    </span>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Performance by Sport & Market */}
                <div className="bg-slate-900/50 rounded-lg p-4 border border-slate-700">
                    <h4 className="text-sm font-bold text-slate-400 uppercase mb-3">By Sport & Market</h4>
                    <div className="space-y-3">
                        {sportPerformance.map(sport => (
                            <div key={sport.sport} className="text-xs">
                                <div className="flex justify-between items-center mb-1">
                                    <span className="text-white font-bold">{sport.sport}</span>
                                    <span className={`font-bold ${sport.winRate >= 55 ? 'text-green-400' : sport.winRate >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
                                        {sport.winRate.toFixed(0)}%
                                    </span>
                                </div>
                                <div className="text-slate-500">{sport.wins}-{sport.losses} ({sport.roi >= 0 ? '+' : ''}{sport.roi.toFixed(1)}% ROI)</div>
                            </div>
                        ))}
                        {marketPerformance.length > 0 && (
                            <>
                                <div className="border-t border-slate-700 pt-2 mt-2"></div>
                                {marketPerformance.map(market => (
                                    <div key={market.market} className="text-xs">
                                        <div className="flex justify-between items-center">
                                            <span className="text-slate-400">{market.market}:</span>
                                            <span className={`font-bold ${market.winRate >= 55 ? 'text-green-400' : market.winRate >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
                                                {market.wins}-{market.losses} ({market.winRate.toFixed(0)}%)
                                            </span>
                                        </div>
                                    </div>
                                ))}
                            </>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default ModelPerformanceAnalytics;
