# Free Sports News API Research

## Best Free Options for NCAAM Injury/Lineup Data

### 1. **SportsDataIO** (Recommended)
- **Coverage**: NCAA College Basketball
- **Features**: Injuries, Lineups & Depth Charts explicitly listed
- **Free Tier**: Free trial available, can request limited production access
- **URL**: https://sportsdata.io/developers/api-documentation/ncaa-basketball
- **Pros**: Most comprehensive, official data
- **Cons**: May require contacting sales for free tier limits

### 2. **API-Sports**
- **Coverage**: NFL & NCAA
- **Features**: Line-ups explicitly mentioned
- **Free Tier**: 100 requests/day per API
- **URL**: https://api-sports.io
- **Pros**: Generous free tier, RESTful API
- **Cons**: Injury data not explicitly confirmed

### 3. **Goalserve**
- **Coverage**: NBA, College, European competitions
- **Features**: Injuries explicitly listed, fixtures, live scores
- **Free Tier**: Free trial period
- **URL**: https://www.goalserve.com/basketball-data-feed
- **Pros**: JSON feed, injury data confirmed
- **Cons**: Trial period only (not permanent free tier)

### 4. **henrygd/ncaa-api** (GitHub)
- **Coverage**: All NCAA sports
- **Features**: Live scores, stats, standings
- **Free Tier**: Completely free, 5 req/sec per IP
- **URL**: https://github.com/henrygd/ncaa-api
- **Pros**: Totally free, can self-host
- **Cons**: Injury/lineup data not explicitly confirmed

## Alternative: Web Scraping

### RotoWire + Covers.com
- **Coverage**: Comprehensive NCAAM injury reports
- **Free Tier**: Public websites (scraping allowed with rate limits)
- **Pros**: Most up-to-date injury news
- **Cons**: Requires web scraping, less reliable

## Recommendation

**Primary**: Use **henrygd/ncaa-api** (GitHub) for general game data
**Secondary**: Scrape **RotoWire** for injury-specific information

### Implementation Plan

1. Use `henrygd/ncaa-api` for:
   - Live scores
   - Team stats
   - Schedules

2. Add lightweight scraper for RotoWire injury page:
   - URL: `https://www.rotowire.com/basketball/injury-report.php`
   - Parse injury table for NCAAM teams
   - Cache results (update every 6 hours)

3. Fallback to SportsDataIO if budget allows

## Code Example

```python
import requests

# Free NCAA API
def get_ncaa_scores():
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
    response = requests.get(url)
    return response.json()

# RotoWire scraper (injury data)
def scrape_rotowire_injuries():
    url = "https://www.rotowire.com/basketball/injury-report.php"
    # Parse HTML for NCAAM section
    # Return list of injured players by team
    pass
```
