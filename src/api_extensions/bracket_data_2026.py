import json

RAW_DATA = r'''{
  "season": "2025-26",
  "rounds": {
    "East": {
      "round_of_64": [
        {
          "team_a": "Duke Blue Devils",
          "team_b": "Siena Saints",
          "spread": -26.67,
          "total": 144.25,
          "win_prob_a": 99.6,
          "win_prob_b": 0.4,
          "winner": "Duke Blue Devils",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Ohio State Buckeyes",
          "team_b": "TCU Horned Frogs",
          "spread": 15.89,
          "total": 151.97,
          "win_prob_a": 6.7,
          "win_prob_b": 93.3,
          "winner": "TCU Horned Frogs",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "St. John's Red Storm",
          "team_b": "Northern Iowa Panthers",
          "spread": -9.28,
          "total": 138.81,
          "win_prob_a": 81.1,
          "win_prob_b": 18.9,
          "winner": "St. John's Red Storm",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Kansas Jayhawks",
          "team_b": "California Baptist Lancers",
          "spread": -8.69,
          "total": 147.18,
          "win_prob_a": 79.6,
          "win_prob_b": 20.4,
          "winner": "Kansas Jayhawks",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Louisville Cardinals",
          "team_b": "South Florida Bulls",
          "spread": -6.92,
          "total": 162.93,
          "win_prob_a": 74.3,
          "win_prob_b": 25.7,
          "winner": "Louisville Cardinals",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Michigan State Spartans",
          "team_b": "North Dakota State Bison",
          "spread": -33.03,
          "total": 156.37,
          "win_prob_a": 99.9,
          "win_prob_b": 0.1,
          "winner": "Michigan State Spartans",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "UCLA Bruins",
          "team_b": "UCF Knights",
          "spread": -4.47,
          "total": 160.64,
          "win_prob_a": 66.1,
          "win_prob_b": 33.9,
          "winner": "UCLA Bruins",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "UConn Huskies",
          "team_b": "Furman Paladins",
          "spread": -19.59,
          "total": 144.28,
          "win_prob_a": 97.0,
          "win_prob_b": 3.0,
          "winner": "UConn Huskies",
          "summary": "MC:10000 | \u03c3:10.5"
        }
      ],
      "round_of_32": [
        {
          "team_a": "Duke Blue Devils",
          "team_b": "TCU Horned Frogs",
          "spread": -14.07,
          "total": 145.51,
          "win_prob_a": 91.0,
          "win_prob_b": 9.0,
          "winner": "Duke Blue Devils",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "St. John's Red Storm",
          "team_b": "Kansas Jayhawks",
          "spread": -1.12,
          "total": 147.23,
          "win_prob_a": 54.0,
          "win_prob_b": 46.0,
          "winner": "St. John's Red Storm",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Louisville Cardinals",
          "team_b": "Michigan State Spartans",
          "spread": 9.05,
          "total": 159.12,
          "win_prob_a": 19.0,
          "win_prob_b": 81.0,
          "winner": "Michigan State Spartans",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "UCLA Bruins",
          "team_b": "UConn Huskies",
          "spread": 4.18,
          "total": 148.77,
          "win_prob_a": 35.0,
          "win_prob_b": 65.0,
          "winner": "UConn Huskies",
          "summary": "MC:10000 | \u03c3:10.5"
        }
      ],
      "sweet_16": [
        {
          "team_a": "Duke Blue Devils",
          "team_b": "St. John's Red Storm",
          "spread": -8.85,
          "total": 148.11,
          "win_prob_a": 79.9,
          "win_prob_b": 20.1,
          "winner": "Duke Blue Devils",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Michigan State Spartans",
          "team_b": "UConn Huskies",
          "spread": -7.04,
          "total": 148.55,
          "win_prob_a": 75.5,
          "win_prob_b": 24.5,
          "winner": "Michigan State Spartans",
          "summary": "MC:10000 | \u03c3:10.5"
        }
      ],
      "elite_8": [
        {
          "team_a": "Duke Blue Devils",
          "team_b": "Michigan State Spartans",
          "spread": -0.36,
          "total": 150.32,
          "win_prob_a": 50.8,
          "win_prob_b": 49.2,
          "winner": "Duke Blue Devils",
          "summary": "MC:10000 | \u03c3:10.5"
        }
      ]
    },
    "South": {
      "round_of_64": [
        {
          "team_a": "Florida Gators",
          "team_b": "Lehigh",
          "spread": -30.38,
          "total": 152.23,
          "win_prob_a": 99.8,
          "win_prob_b": 0.2,
          "winner": "Florida Gators",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Clemson Tigers",
          "team_b": "Iowa Hawkeyes",
          "spread": 2.03,
          "total": 142.14,
          "win_prob_a": 43.0,
          "win_prob_b": 57.0,
          "winner": "Iowa Hawkeyes",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Vanderbilt Commodores",
          "team_b": "McNeese Cowboys",
          "spread": -10.56,
          "total": 156.01,
          "win_prob_a": 84.1,
          "win_prob_b": 15.9,
          "winner": "Vanderbilt Commodores",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Nebraska Cornhuskers",
          "team_b": "Troy Trojans",
          "spread": -15.98,
          "total": 144.18,
          "win_prob_a": 93.4,
          "win_prob_b": 6.6,
          "winner": "Nebraska Cornhuskers",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "North Carolina Tar Heels",
          "team_b": "VCU Rams",
          "spread": -2.65,
          "total": 159.27,
          "win_prob_a": 60.0,
          "win_prob_b": 40.0,
          "winner": "North Carolina Tar Heels",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Illinois Fighting Illini",
          "team_b": "Penn Quakers",
          "spread": -21.28,
          "total": 155.74,
          "win_prob_a": 97.8,
          "win_prob_b": 2.2,
          "winner": "Illinois Fighting Illini",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Saint Mary's Gaels",
          "team_b": "Texas A&M Aggies",
          "spread": -3.07,
          "total": 153.59,
          "win_prob_a": 61.3,
          "win_prob_b": 38.7,
          "winner": "Saint Mary's Gaels",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Houston Cougars",
          "team_b": "Idaho Vandals",
          "spread": -20.97,
          "total": 144.68,
          "win_prob_a": 97.8,
          "win_prob_b": 2.2,
          "winner": "Houston Cougars",
          "summary": "MC:10000 | \u03c3:10.5"
        }
      ],
      "round_of_32": [
        {
          "team_a": "Florida Gators",
          "team_b": "Iowa Hawkeyes",
          "spread": -7.83,
          "total": 151.54,
          "win_prob_a": 77.6,
          "win_prob_b": 22.4,
          "winner": "Florida Gators",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Vanderbilt Commodores",
          "team_b": "Nebraska Cornhuskers",
          "spread": -1.35,
          "total": 153.28,
          "win_prob_a": 55.2,
          "win_prob_b": 44.8,
          "winner": "Vanderbilt Commodores",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "North Carolina Tar Heels",
          "team_b": "Illinois Fighting Illini",
          "spread": 7.53,
          "total": 160.73,
          "win_prob_a": 24.1,
          "win_prob_b": 75.9,
          "winner": "Illinois Fighting Illini",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Saint Mary's Gaels",
          "team_b": "Houston Cougars",
          "spread": 6.71,
          "total": 142.65,
          "win_prob_a": 26.3,
          "win_prob_b": 73.7,
          "winner": "Houston Cougars",
          "summary": "MC:10000 | \u03c3:10.5"
        }
      ],
      "sweet_16": [
        {
          "team_a": "Florida Gators",
          "team_b": "Vanderbilt Commodores",
          "spread": -4.1,
          "total": 161.92,
          "win_prob_a": 65.7,
          "win_prob_b": 34.3,
          "winner": "Florida Gators",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Illinois Fighting Illini",
          "team_b": "Houston Cougars",
          "spread": 0.76,
          "total": 151.46,
          "win_prob_a": 46.9,
          "win_prob_b": 53.1,
          "winner": "Houston Cougars",
          "summary": "MC:10000 | \u03c3:10.5"
        }
      ],
      "elite_8": [
        {
          "team_a": "Florida Gators",
          "team_b": "Houston Cougars",
          "spread": -0.53,
          "total": 148.43,
          "win_prob_a": 51.8,
          "win_prob_b": 48.2,
          "winner": "Florida Gators",
          "summary": "MC:10000 | \u03c3:10.5"
        }
      ]
    },
    "West": {
      "round_of_64": [
        {
          "team_a": "Arizona Wildcats",
          "team_b": "Long Island Sharks",
          "spread": -0.08,
          "total": 144.87,
          "win_prob_a": 50.5,
          "win_prob_b": 49.5,
          "winner": "Arizona Wildcats",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Villanova Wildcats",
          "team_b": "Utah State Aggies",
          "spread": -10.58,
          "total": 154.08,
          "win_prob_a": 84.2,
          "win_prob_b": 15.8,
          "winner": "Villanova Wildcats",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Wisconsin Badgers",
          "team_b": "High Point Panthers",
          "spread": -10.6,
          "total": 167.34,
          "win_prob_a": 83.7,
          "win_prob_b": 16.3,
          "winner": "Wisconsin Badgers",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Arkansas Razorbacks",
          "team_b": "Hawaii Rainbow Warriors",
          "spread": -13.65,
          "total": 159.19,
          "win_prob_a": 90.6,
          "win_prob_b": 9.4,
          "winner": "Arkansas Razorbacks",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "BYU Cougars",
          "team_b": "NC State",
          "spread": -2.42,
          "total": 169.82,
          "win_prob_a": 59.3,
          "win_prob_b": 40.7,
          "winner": "BYU Cougars",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Gonzaga Bulldogs",
          "team_b": "Kennesaw State Owls",
          "spread": 0.04,
          "total": 144.97,
          "win_prob_a": 49.6,
          "win_prob_b": 50.4,
          "winner": "Kennesaw State Owls",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Miami (FL) Hurricanes",
          "team_b": "Missouri Tigers",
          "spread": -3.57,
          "total": 156.43,
          "win_prob_a": 62.8,
          "win_prob_b": 37.2,
          "winner": "Miami (FL) Hurricanes",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Purdue Boilermakers",
          "team_b": "Queens (N.C.) Royals",
          "spread": -21.44,
          "total": 169.3,
          "win_prob_a": 98.1,
          "win_prob_b": 1.9,
          "winner": "Purdue Boilermakers",
          "summary": "MC:10000 | \u03c3:10.5"
        }
      ],
      "round_of_32": [
        {
          "team_a": "Arizona Wildcats",
          "team_b": "Villanova Wildcats",
          "spread": -11.96,
          "total": 152.99,
          "win_prob_a": 87.0,
          "win_prob_b": 13.0,
          "winner": "Arizona Wildcats",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Wisconsin Badgers",
          "team_b": "Arkansas Razorbacks",
          "spread": 1.13,
          "total": 171.5,
          "win_prob_a": 45.7,
          "win_prob_b": 54.3,
          "winner": "Arkansas Razorbacks",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "BYU Cougars",
          "team_b": "Kennesaw State Owls",
          "spread": 0.06,
          "total": 145.05,
          "win_prob_a": 49.7,
          "win_prob_b": 50.3,
          "winner": "Kennesaw State Owls",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Miami (FL) Hurricanes",
          "team_b": "Purdue Boilermakers",
          "spread": 6.61,
          "total": 159.77,
          "win_prob_a": 26.5,
          "win_prob_b": 73.5,
          "winner": "Purdue Boilermakers",
          "summary": "MC:10000 | \u03c3:10.5"
        }
      ],
      "sweet_16": [
        {
          "team_a": "Arizona Wildcats",
          "team_b": "Arkansas Razorbacks",
          "spread": -8.46,
          "total": 166.06,
          "win_prob_a": 79.1,
          "win_prob_b": 20.9,
          "winner": "Arizona Wildcats",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Kennesaw State Owls",
          "team_b": "Purdue Boilermakers",
          "spread": 0.12,
          "total": 145.03,
          "win_prob_a": 49.3,
          "win_prob_b": 50.7,
          "winner": "Purdue Boilermakers",
          "summary": "MC:10000 | \u03c3:10.5"
        }
      ],
      "elite_8": [
        {
          "team_a": "Arizona Wildcats",
          "team_b": "Purdue Boilermakers",
          "spread": -4.8,
          "total": 159.64,
          "win_prob_a": 67.5,
          "win_prob_b": 32.5,
          "winner": "Arizona Wildcats",
          "summary": "MC:10000 | \u03c3:10.5"
        }
      ]
    },
    "Midwest": {
      "round_of_64": [
        {
          "team_a": "Michigan Wolverines",
          "team_b": "Howard",
          "spread": -29.35,
          "total": 149.09,
          "win_prob_a": 99.7,
          "win_prob_b": 0.3,
          "winner": "Michigan Wolverines",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Georgia Bulldogs",
          "team_b": "Saint Louis Billikens",
          "spread": -1.36,
          "total": 169.36,
          "win_prob_a": 55.3,
          "win_prob_b": 44.7,
          "winner": "Georgia Bulldogs",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Texas Tech Red Raiders",
          "team_b": "Akron Zips",
          "spread": -8.36,
          "total": 162.72,
          "win_prob_a": 78.6,
          "win_prob_b": 21.4,
          "winner": "Texas Tech Red Raiders",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Alabama Crimson Tide",
          "team_b": "Hofstra Pride",
          "spread": -11.22,
          "total": 165.67,
          "win_prob_a": 85.6,
          "win_prob_b": 14.4,
          "winner": "Alabama Crimson Tide",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Tennessee Volunteers",
          "team_b": "SMU",
          "spread": -5.38,
          "total": 155.12,
          "win_prob_a": 69.3,
          "win_prob_b": 30.7,
          "winner": "Tennessee Volunteers",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Virginia Cavaliers",
          "team_b": "Wright State Raiders",
          "spread": -0.11,
          "total": 144.91,
          "win_prob_a": 50.5,
          "win_prob_b": 49.5,
          "winner": "Virginia Cavaliers",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Kentucky Wildcats",
          "team_b": "Santa Clara Broncos",
          "spread": -1.62,
          "total": 162.06,
          "win_prob_a": 56.0,
          "win_prob_b": 44.0,
          "winner": "Kentucky Wildcats",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Iowa State Cyclones",
          "team_b": "Tennessee State Tigers",
          "spread": 2.36,
          "total": 144.37,
          "win_prob_a": 41.3,
          "win_prob_b": 58.7,
          "winner": "Tennessee State Tigers",
          "summary": "MC:10000 | \u03c3:10.5"
        }
      ],
      "round_of_32": [
        {
          "team_a": "Michigan Wolverines",
          "team_b": "Georgia Bulldogs",
          "spread": -12.64,
          "total": 165.61,
          "win_prob_a": 88.5,
          "win_prob_b": 11.5,
          "winner": "Michigan Wolverines",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Texas Tech Red Raiders",
          "team_b": "Alabama Crimson Tide",
          "spread": 0.47,
          "total": 170.98,
          "win_prob_a": 48.0,
          "win_prob_b": 52.0,
          "winner": "Alabama Crimson Tide",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Tennessee Volunteers",
          "team_b": "Virginia Cavaliers",
          "spread": 0.29,
          "total": 145.64,
          "win_prob_a": 48.8,
          "win_prob_b": 51.2,
          "winner": "Virginia Cavaliers",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Kentucky Wildcats",
          "team_b": "Tennessee State Tigers",
          "spread": 2.96,
          "total": 149.15,
          "win_prob_a": 39.0,
          "win_prob_b": 61.0,
          "winner": "Tennessee State Tigers",
          "summary": "MC:10000 | \u03c3:10.5"
        }
      ],
      "sweet_16": [
        {
          "team_a": "Michigan Wolverines",
          "team_b": "Alabama Crimson Tide",
          "spread": -9.21,
          "total": 169.87,
          "win_prob_a": 80.0,
          "win_prob_b": 20.0,
          "winner": "Michigan Wolverines",
          "summary": "MC:10000 | \u03c3:10.5"
        },
        {
          "team_a": "Virginia Cavaliers",
          "team_b": "Tennessee State Tigers",
          "spread": -0.37,
          "total": 145.46,
          "win_prob_a": 51.5,
          "win_prob_b": 48.5,
          "winner": "Virginia Cavaliers",
          "summary": "MC:10000 | \u03c3:10.5"
        }
      ],
      "elite_8": [
        {
          "team_a": "Michigan Wolverines",
          "team_b": "Virginia Cavaliers",
          "spread": -8.01,
          "total": 151.58,
          "win_prob_a": 77.5,
          "win_prob_b": 22.5,
          "winner": "Michigan Wolverines",
          "summary": "MC:10000 | \u03c3:10.5"
        }
      ]
    }
  },
  "final_four": [
    {
      "team_a": "Duke Blue Devils",
      "team_b": "Arizona Wildcats",
      "spread": -0.93,
      "total": 150.72,
      "win_prob_a": 53.7,
      "win_prob_b": 46.3,
      "winner": "Duke Blue Devils",
      "summary": "MC:10000 | \u03c3:10.5"
    },
    {
      "team_a": "Florida Gators",
      "team_b": "Michigan Wolverines",
      "spread": 3.15,
      "total": 156.16,
      "win_prob_a": 38.5,
      "win_prob_b": 61.5,
      "winner": "Michigan Wolverines",
      "summary": "MC:10000 | \u03c3:10.5"
    }
  ],
  "championship": {
    "team_a": "Duke Blue Devils",
    "team_b": "Michigan Wolverines",
    "spread": -0.4,
    "total": 150.41,
    "win_prob_a": 50.9,
    "win_prob_b": 49.1,
    "winner": "Duke Blue Devils",
    "summary": "MC:10000 | \u03c3:10.5"
  },
  "champion": "Duke Blue Devils"
}'''

DATA = json.loads(RAW_DATA)