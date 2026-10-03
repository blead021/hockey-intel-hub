// Plain-language definitions for column headings and stat labels, shown by the "i" icon next to each label.
// Keys are the label as it appears on the page. A few labels mean different things in different tables; those
// pages pass an explicit key (for example "GS (goalie)").

export const GLOSSARY: Record<string, string> = {
  // Basic stats
  GV: "Giveaways: times he lost the puck to the other team.",
  TK: "Takeaways: times he took the puck from the other team.",
  GS: "Game Score: our measure of his overall impact in one game, in goals compared with an average player given the same ice time. Positive is good.",
  "GS/GP": "Game Score per game: our measure of overall impact, in goals compared with an average player given the same ice time.",
  "Game Score": "Our measure of overall impact per game, in goals compared with an average player given the same ice time. It adds up even-strength play, special teams, finishing, playmaking, penalties, and faceoffs (goalies: goals saved above expected). Positive is good.",

  // Goalies
  GSAx: "Goals saved above expected: goals our expected goals model predicted on the shots he faced, minus goals he allowed. Positive means he stopped more than an average goalie would have.",
  xGA: "Expected goals against: how many goals an average goalie would have allowed on the shots he faced, from our expected goals model.",
  "GSAx (game)": "Goals saved above expected in this game: expected goals against minus goals allowed. Positive means he stopped more than an average goalie would have.",
  "HD saves": "High-danger saves: high-danger shots on goal he stopped, out of all high-danger shots on goal he faced. High-danger shots are worth 0.15 expected goals or more, mostly from in close.",
  "GSAx/60": "Goals saved above expected per 60 minutes played, so goalies with different workloads can be compared.",
  "HDSV%": "High-danger save percentage: saves on high-danger shots (worth 0.15 expected goals or more, mostly from in close) divided by high-danger shots on goal.",
  "HD GSAx": "Goals saved above expected on high-danger shots only: how he did on the hardest chances compared with an average goalie.",
  "5v5 GSAx": "Goals saved above expected at 5-on-5 only, leaving out power plays and penalty kills.",
  "EV SV%": "Even-strength save percentage: save percentage when both teams had the same number of skaters.",
  "Quality start %": "Share of his starts that were quality starts: a save percentage above the league average that season, or at least .885 when facing 20 shots or fewer.",
  "Really bad start %": "Share of his starts with a save percentage below .850. Lower is better.",
  "xGA/60": "Expected goals against per 60 minutes: how dangerous the shots he faced were. Higher means a harder workload. This describes his team's defense in front of him, not his own play.",

  // Advanced (5v5 unless noted)
  "xGF%": "Expected goals share: of all the expected goals for and against while he was on the ice at 5-on-5, the share his team had. Expected goals rate each shot's chance of scoring (location, shot type, rebounds, rushes) using our own model. 50% is even; higher is better.",
  "5v5 xGF%": "Expected goals share at 5-on-5: the team's share of expected goals for and against. Expected goals rate each shot's chance of scoring. 50% is even; higher is better.",
  "Relative xGF%": "His xGF% minus his team's xGF% when he was on the bench, in percentage points. Positive means the team controls scoring chances better with him on the ice than without him.",
  "Relative CF%": "His CF% minus his team's CF% when he was on the bench, in percentage points. Positive means the team has the puck more (out-shoots the other team) with him on the ice than without him.",
  "HDCF%": "High-danger chances share: like xGF%, but counting only dangerous shots (an expected goal value of 0.15 or more, mostly from in close).",
  "CF%": "Corsi for percentage: the share of all 5-on-5 shot attempts (goals, shots on goal, misses, and blocked shots) taken by his team while he was on the ice. A common measure of puck possession. 50% is even.",
  "FF%": "Fenwick for percentage: like CF%, but leaving out blocked shots.",
  "GF%": "Goals for percentage: the share of actual 5-on-5 goals scored by his team while he was on the ice.",
  "CF/60": "Shot attempts by his team per 60 minutes of his 5-on-5 ice time. Higher is better.",
  "CA/60": "Shot attempts against his team per 60 minutes of his 5-on-5 ice time. Lower is better.",
  "ixG/60": "Individual expected goals per 60 minutes: the scoring chance value of his own shots, all strengths. Shows how many good chances he gets, regardless of whether they go in.",
  "Goals above expected": "Goals minus the expected goals on his own shots, all strengths. Positive means he finished better than a typical shooter would on the same shots (skill, or luck).",
  IPP: "Individual points percentage: the share of his team's 5-on-5 goals while he was on the ice that he scored or assisted on.",
  PDO: "On-ice shooting percentage plus on-ice save percentage, scaled so 100 is average. Far above or below 100 usually means luck that tends to even out.",
  "OZS%": "Offensive zone start percentage: of his shifts that began with a faceoff in the offensive or defensive zone, the share in the offensive zone. A measure of how the coach uses him, not of quality.",
  WAR: "Wins above replacement (PuckSleuth's estimate): how many wins he adds compared with a replacement-level player, the kind a team can call up or sign cheaply. Built from our Game Score.",

  // Contracts and value
  "Cap / yrs": "Cap hit and years left on his contract.",
  "Cap %": "Cap hit as a share of that season's salary cap ceiling. Comparing shares rather than dollars keeps deals signed under different caps comparable.",
  Yrs: "Years left on the contract, including this season.",
  Term: "Years left on the contract, including this season.",
  Expiry: "What happens when the contract ends. UFA (unrestricted free agent): he can sign with any team. RFA (restricted free agent): his team keeps his rights and can match offers.",
  Surplus: "Surplus value is what his play would be worth on the open market minus his cap hit. Positive means he is a bargain; negative means he is paid more than his play is worth. How we estimate it: (1) project his WAR for a full 84-game season mostly from this season and last season, with the season before counting a little, pulled slightly toward replacement level when he has played few games, and adjusted for his age using our age curve; (2) turn that into a market cap hit using what veterans 27 and older at his position, with similar projected WAR and scoring, are paid as a share of the salary cap; goalies are valued by rank instead: a goalie projected 5th-best is worth what the 5th-highest-paid veteran goalie earns, since goalie numbers swing a lot from year to year; (3) subtract his actual cap hit. Entry-level and young players' contracts are left out of the market comparison, since they are not set by the open market. Needs 40 games over three seasons.",
  "Surplus value": "Surplus value is what his play would be worth on the open market minus his cap hit. Positive means he is a bargain; negative means he is paid more than his play is worth. How we estimate it: (1) project his WAR for a full 84-game season mostly from this season and last season, with the season before counting a little, pulled slightly toward replacement level when he has played few games, and adjusted for his age using our age curve; (2) turn that into a market cap hit using what veterans 27 and older at his position, with similar projected WAR and scoring, are paid as a share of the salary cap; goalies are valued by rank instead: a goalie projected 5th-best is worth what the 5th-highest-paid veteran goalie earns, since goalie numbers swing a lot from year to year; (3) subtract his actual cap hit. Entry-level and young players' contracts are left out of the market comparison, since they are not set by the open market. Needs 40 games over three seasons.",
  Space: "Cap space: the salary cap ceiling minus everything the team's contracts count against the cap this season.",
  "Cap space": "The salary cap ceiling minus everything the team's contracts count against the cap this season (roster, injured players, players in the minors above the buried allowance, retained salary, and dead cap).",
  "Cap committed": "Everything the team's contracts count against the cap this season.",
  "Active roster": "Players on the NHL roster now. Teams may carry up to 23 players and hold up to 50 contracts.",
  "PP% / PK%": "Power play percentage (share of power plays that produced a goal) and penalty kill percentage (share of opponents' power plays killed off).",

  // Sentiment
  Fans: "Fan sentiment, 0 to 100: how positively fans talk about him in posts and comments over the last four weeks, with recent days weighted more. 50 is neutral.",
  "Fan sentiment": "How positively fans talk about the team's players in posts and comments over the last four weeks, 0 to 100. 50 is neutral.",
  Beat: "Beat writer sentiment, 0 to 100: how positively the reporters who cover the team write about him. 50 is neutral.",
  Chatter: "Trade chatter: mentions of him in trade talk over the last 7 days. An arrow shows whether it is rising or fading.",

  // League page
  "Goals (grade)": "Goal scoring grade: goals per game compared with the other 31 teams.",
  "Creation (grade)": "Playmaking grade: primary assists per game compared with the other 31 teams.",
  "Physical (grade)": "Physicality grade: hits plus blocked shots per game compared with the other 31 teams.",
  "5v5 D (grade)": "5-on-5 defense grade: expected goals allowed per 60 minutes at 5-on-5 (fewer is better) compared with the other 31 teams.",
  "PP (grade)": "Power play grade: power play percentage compared with the other 31 teams.",
  "PK (grade)": "Penalty kill grade: penalty kill percentage compared with the other 31 teams.",
  "Goalie (grade)": "Goaltending grade: goals saved above expected per game compared with the other 31 teams.",
  "Perf.": "Performance percentile, 0 to 100: how his play ranks against players at his position, blending 5-on-5 expected goals share, WAR, and Game Score.",
  "Perception gap": "Performance percentile minus fan sentiment percentile. A big positive gap means he plays better than fans give him credit for.",
  "Best fits": "Teams that are weak (graded Need or Thin) in his strongest area and have the cap space to take him on, with up to 50% of his salary retained.",

  // Trade Targets
  "Team status": "Contender, Bubble, or Seller, from our power rating (points, goal differential, and expected goals share, blended with last season early on). Sellers are named only after 20 games.",
  "Cap fit": "Whether he fits under the chosen team's cap space, and if not, how much of his salary his current team would need to keep (retain) for him to fit. Teams can retain at most 50%.",
  Fills: "How well he fills the chosen team's weak spots: his percentile at his position in the team's best-matching Need or Thin category.",
  Signal: "Buy-low: plays better than his results show, with bad luck. Value: surplus value of $1.5M or more. Risk: costs $2M or more above his value. Rental: expiring UFA, 30 or older. Contract yr: last year of his deal.",

  // Player page EDGE skating
  "Top speed": "His fastest skating speed this season, from NHL EDGE tracking.",
  "20+ mph bursts": "Number of times he reached 20 mph or faster this season, from NHL EDGE tracking.",
  "Hardest shot": "His hardest shot this season, from NHL EDGE tracking.",
  Distance: "Total distance skated this season, from NHL EDGE tracking.",
  "OZ time": "Share of his time on ice spent in the offensive zone, from NHL EDGE tracking.",
  "DZ time": "Share of his time on ice spent in the defensive zone, from NHL EDGE tracking.",

  // Play style traits (percentiles vs. his position group)
  "Shooting volume": "Shots on goal plus missed shots per 60 minutes, all strengths.",
  Playmaking: "Primary assists per 60 minutes, all strengths.",
  "Zone entries": "An estimate until tracking data is added: rush shot attempts (shots within 4 seconds of play coming out of the neutral or defensive zone) he took or was on the ice for, per 60 minutes at 5-on-5.",
  Forechecking: "His hits and takeaways in the offensive zone, per 60 minutes.",
  Physicality: "Hits plus blocked shots per 60 minutes, all strengths.",
  "Defensive impact": "Expected goals against per 60 minutes at 5-on-5 with him on the ice, compared with his team when he is on the bench. Fewer against ranks higher.",
  "Puck management": "Takeaways minus giveaways per 60 minutes.",
  Speed: "Average of his NHL EDGE top-speed percentile and his 20+ mph bursts per game percentile.",

  // Game Score parts
  "Even strength offense": "Expected goals his team created at 5-on-5 while he was on the ice, compared with the league rate for his ice time.",
  "Even strength defense": "Expected goals his team allowed at 5-on-5 while he was on the ice, compared with the league rate (fewer allowed adds to his score).",
  "Power play": "His team's expected goals for and against on the power play while he was on the ice, compared with the league rate.",
  "Penalty kill": "His team's expected goals for and against on the penalty kill while he was on the ice, compared with the league rate.",
  "Playmaking (Game Score)": "Primary assists above the league rate for his ice time, each worth half a goal.",
  Media: "Media sentiment, 0 to 100: how positively national and local news coverage talks about him. 50 is neutral.",
  Finishing: "Goals minus the expected goals on his own shots.",
  Penalties: "Penalties drawn minus penalties taken, each worth about 0.19 goals.",
  Faceoffs: "Faceoffs won minus lost, each worth 0.01 goals.",
  Goaltending: "Goals saved above expected.",
};

export function definition(label: string | undefined | null): string | undefined {
  return label ? GLOSSARY[label] : undefined;
}
