import statistics

def normal_cdf(x, mu, sigma):
    from statistics import NormalDist
    return NormalDist(mu, sigma).cdf(x)

# Example: Home team is a 6 point favorite
# Standard betting convention: spread_home = -6.0
mu_spread_final = -6.0
sigma_spread = 10.0

prob_home_raw_current = 1.0 - normal_cdf(0.0, mu_spread_final, sigma_spread)
prob_away_current = 1.0 - prob_home_raw_current

print(f"Current Logic:")
print(f"Spread = {mu_spread_final} (Home Favorite)")
print(f"P(Home Win) = {prob_home_raw_current:.3f}")
print(f"P(Away Win) = {prob_away_current:.3f}")

# Proposed Fixed Logic
# If mu_spread_final is -6.0, then expected home margin is +6.0
# P(Margin > 0) = 1.0 - CDF(0, ExpectedMargin, Sigma)
expected_margin_home = -mu_spread_final
prob_home_fixed = 1.0 - normal_cdf(0.0, expected_margin_home, sigma_spread)
prob_away_fixed = 1.0 - prob_home_fixed

print(f"\nFixed Logic:")
print(f"P(Home Win) = {prob_home_fixed:.3f}")
print(f"P(Away Win) = {prob_away_fixed:.3f}")
