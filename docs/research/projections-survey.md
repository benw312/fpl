# FPL Points-Projection Methodologies and Open-Source Implementations (2026): A Design Brief for `domain/projections.py`

## TL;DR
- **Build the standard xP decomposition, not a monolithic model.** Every serious public model — AIrsenal, OpenFPL, FPL Review, FPL Form — decomposes projected points into P(appearance)×minutes, attacking returns from per-90 xG/xA scaled by fixture, a team-level clean-sheet/goals-conceded model, save points, bonus, and (since 2025/26) defensive-contribution points. Crib this structure; it insulates the optimiser and lets you improve one component at a time.
- **Your API observations reflect real, known 2026/27 API behaviour, not a bug.** `ep_next` compression, FDR being an opponent+venue lookup, and the zeroed `strength_attack/defence` fields mean you must derive team strength yourself. The community's canonical route is a Dixon-Coles Poisson model fitted on season-to-date goals (with a documented decay of ξ≈0.0065 per half-week ≈ 0.00186/day, from Dixon & Coles 1997, and a fittable multiplicative home advantage seeded near 1.2), falling back to FDR bands for the first ~4-6 gameweeks.
- **Licences are permissive enough to crib freely, but there is NO published empirical grounding for FDR-band multipliers.** OpenFPL (MIT), AIrsenal (MIT), FPL-Optimization-Tools (Apache-2.0) and vaastav's data repo (MIT, code only) are all safe to learn structure and constants from. Your reviewer's 1.15→0.85 band multipliers are a reasonable monotone heuristic but have no citable empirical basis — either derive them yourself from vaastav's archive or label them as heuristic priors.

## Key Findings

### 1. The public model landscape is documented at the level of *structure*, not *coefficients*
- **FPL Review (Massive Data Model, "v4" for 2025/26)** is the acknowledged commercial benchmark. Its documentation states it "combines traditional statistical methods and machine learning techniques" projecting Expected Value across up to 14 gameweeks, integrating "historical performance data, market odds, tactical analysis." The author's own backtests claim it beats bookmaker-implied goalscoring probabilities. Crucially, **inner workings and coefficients are undisclosed and paywalled** — you can crib the *decomposition philosophy* but no numbers.
- **AIrsenal (Alan Turing Institute)** is the single best open-source model to crib from because it is fully documented AND its methodology matches your constraints: a Bayesian Dixon-Coles team model + a player-level goal-involvement model + minutes heuristics. It is the only prominent model that publishes its team-strength approach in prose.
- **OpenFPL (Groos, 2025, arXiv:2508.09992v1, 29 Jul 2025)** is the most rigorous open academic model: position-specific ensembles of XGBoost + Random Forest, trained on FPL + Understat data from 2020-21 to 2023-24. Per its abstract, "OpenFPL achieves accuracy comparable to a leading commercial service when tested prospectively on data from the 2024-25 season. OpenFPL also surpasses the commercial benchmark for high-return players (>2 points), which are most influential for rank gains." It is MIT-licensed with released weights. But it depends on Understat (a third-party feed), so it violates your runtime constraint — treat it as a source of feature lists and evaluation benchmarks, not a drop-in.
- **FPL Form, FPL Review xMins, FPL Kiwi, Tor Mikkel Tokvam's Transfer Algorithm** publish methodology at a descriptive level only. FPL Form documents that it computes "team vulnerability to FPL points in the player's position" using opposition "scoriness" (xG-based) and "porosity" (xGA-based) — a useful, replicable idea. FPL Review's xMins is described as an average over 1,000 simulations factoring rotation, injury and tactics (proprietary). Tokvam's Transfer Algorithm is Patreon-gated with no public coefficients.
- **Distinguish clearly:** the *only* fully documented, coefficient-level open models are AIrsenal (prose + code) and OpenFPL (code + weights + paper). Everything else is either marketing-level description or community reverse-engineering.

### 2. Open-source implementations, licences, and cribbability

| Repo | Language | Licence | Method | Runs on official API alone? | Maintained 2026? | Crib value |
|---|---|---|---|---|---|---|
| **alan-turing-institute/AIrsenal** | Python | MIT | Bayesian Dixon-Coles team model + player goal-involvement + minutes heuristics | Yes (FPL API + bundled 3-season history) | Yes | **Highest** — structure, priors, Dixon-Coles home advantage |
| **daniegr/OpenFPL** | Python | MIT | Position-specific XGBoost+RF ensembles | No (needs Understat) | Yes (2025 release) | Feature sets, evaluation benchmarks |
| **sertalpbilal/FPL-Optimization-Tools** (now solioanalytics/open-fpl-solver) | Python | Apache-2.0 | MILP/LP optimiser (HiGHS), *consumes* external projections | Optimiser only | Yes | Optimiser patterns, `decay_base=0.84` objective |
| **vaastav/Fantasy-Premier-League** | Python/CSV | MIT (code); data is FPL/Understat property | Historical data archive | Data repo | Yes | **Last-season carryover data** for priors |
| **olbauday/FPL-Core-Insights** | CSV | Open-data (attribution requested) | FPL API + Opta-like stats + ClubElo, incl. 2026/27 | Data repo | Yes | 2026/27 data + Elo ratings, promoted clubs from day one |
| **sertalpbilal/fpl_optimized** | Python | EPL-2.0 + commercial clause | Daily optimised squads | — | Yes | Avoid for reuse (restrictive; "contact info@fploptimized.com to negotiate a commercial license") |

- **Licence bottom line:** MIT and Apache-2.0 permit reuse of code and constants with attribution. You may legally hardcode coefficients derived from AIrsenal, OpenFPL, or the Apache-2.0 solver. vaastav's MIT covers the *code* only — the LICENSE explicitly states the data "is property of fantasy.premierleague.com and understat.com. I don't own any of the data." So you may compute priors from that archive at build time, but don't redistribute the raw data as if it were yours. Note the important distinction: `sertalpbilal/fpl_optimized` (daily squads) is EPL-2.0 with a commercial clause and should be avoided; the tools/solver repo you want is Apache-2.0.
- **AIrsenal's Dixon-Coles specifics (from the Turing blog + the `bpl`/`bpl-next` package):** every team has α (attack) and β (defence) latent abilities plus γ (home advantage). The model uses a bivariate hierarchical prior on (α,β) with correlation ρ (strong-attacking teams tend to defend well), plus the Dixon-Coles τ low-score correction. Promoted teams are handled via optional team-level covariates X_i and hierarchical shrinkage toward the league mean. Current AIrsenal uses `bpl-next` (numpyro/JAX).

### 3. The standard xP decomposition (and which API fields support each term)

Projected points for a (player, fixture) = the sum of:
1. **Appearance points:** P(play ≥1 min)×1 + P(play ≥60 min)×1, driven by an expected-minutes model. API: `minutes` history (element-summary), `status`, `chance_of_playing_next_round`.
2. **Attacking returns:** per-90 xG → goals (×position points: GK/DEF 6, MID 5, FWD 4); per-90 xA → assists (×3). Scaled by expected minutes and fixture. API: `expected_goals_per_90`, `expected_assists_per_90`, `expected_goal_involvements_per_90` (bootstrap + element-summary).
3. **Clean sheets:** team-level clean-sheet probability × 4 (GK/DEF) or ×1 (MID). API: derived from your own team model / `expected_goals_conceded`, `expected_goals_conceded_per_90`.
4. **Goals-conceded deductions:** −1 per 2 goals conceded (GK/DEF), from expected goals against.
5. **Save points:** GK only, +1 per 3 saves; expected saves from opponent shots on target. API: `saves`, `expected_goals_conceded`; element-summary also now exposes `xgot_faced`, `goals_prevented`, `sweeper_actions`.
6. **Bonus points:** BPS-based or heuristic per-xGI approximation. API: `bps`, `bonus`, `ict_index`.
7. **Defensive-contribution points (NEW 2025/26, confirmed unchanged for 2026/27):** +2 if a **defender** records ≥10 CBIT (clearances, blocks, interceptions, tackles); +2 if a **midfielder/forward** records ≥12 CBIRT (adds ball recoveries). Capped at +2/match regardless of volume; GKs ineligible. API: `defensive_contributions` and `clearances_blocks_interceptions` fields now exist (for defenders they currently track the same numbers); model as P(hit threshold)×2 from per-match history.
8. **Minor terms:** penalties missed (−2), yellow (−1)/red (−3) cards, own goals (−2), penalty saves (+5 GK). Card deductions are best modelled as small season-averaged constants.

### 4. Deriving team strength without the strength fields
- **Dixon-Coles (1997) is the community standard.** Fit a bivariate Poisson on season-to-date results (home/away goals from the fixtures endpoint), with a low-score correction (τ) and exponential time decay. Home scoring rate λ = α_home × β_away × γ; away rate μ = α_away × β_home.
- **Time decay:** the canonical value is **ξ = 0.0065 per half-week** (Dixon & Coles 1997, *Modelling Association Football Scores and Inefficiencies in the Football Betting Market*, JRSS Series C 46(2):265–280), which converts to ≈0.00186/day (a half-life of ≈one year, per opisthokonta.net: "if we divide their value by the number of days in a half week (3.5 days) we get 0.00186"). Practitioners tune ξ by maximising out-of-sample predictive log-likelihood; published EPL optima range widely with data window — dashee87 found ≈0.00325/day, opisthokonta ≈0.0018/day, and artiebits reports 0.012/half-week for EPL 2010/11–2020/21, with the explicit caveat "the best rate depends on your dataset size... you must tune it yourself."
- **Home advantage:** model as a multiplicative γ on the home scoring rate. The AIrsenal/Turing blog confirms the α/β/γ structure ("every team has two latent abilities; α for attack and β for defence. Another parameter γ encapsulates 'home advantage'") but does **not** publish a numeric γ; comparable public Bayesian Dixon-Coles fits report ~1.2 multiplicative or ~0.225 additive goals. **Seed γ≈1.2 and treat it as fittable.** Note the well-documented **decline in Premier League home advantage**: historically ≈0.3 goals/game (≈0.34 excluding the empty-stadium 2020/21 season), but a 2024/25 in-season analysis found just 0.04 goals/game that term, and a long-run study put 2025 at ≈0.25 goals — so do not hardcode a fixed value.
- **xG-based alternative:** aggregate player `expected_goals`/`expected_goals_conceded` per team for a ratings signal that stabilises faster than actual goals early-season (essentially FPL Form's "scoriness/porosity" approach).
- **First few gameweeks:** before results accrue, use FDR-band priors and/or last-season carryover. **Last season's data is NOT in the official API once the new season starts**, but vaastav's archive (MIT code, data caveat) and olbauday/FPL-Core-Insights (includes 2026/27 + ClubElo ratings) have it. Promoted teams for 2026/27 — **Coventry City, Ipswich Town, and Hull City** — need an empirical promoted-team baseline; AIrsenal handles the analogous problem via hierarchical shrinkage plus team covariates.
- **Practical scipy fit:** with ~380 fixtures/season you have ample data by mid-season but very little in GW1-5. Fit ~41 parameters (20 attack + 20 defence + γ, with a sum-to-one identifiability constraint on attack or defence) by minimising the negative weighted log-likelihood with `scipy.optimize.minimize` (L-BFGS-B), applying the τ correction to the four low-score cells (0-0, 1-0, 0-1, 1-1). Early season, regularise toward priors.

### 5. Concrete coefficients with provenance
- **Home advantage:** structure α/β/γ from AIrsenal; seed multiplicative γ≈1.2 (public Bayesian Dixon-Coles fits) or additive ≈0.225–0.30 goals — **fittable, not fixed.**
- **Time decay:** ξ=0.0065/half-week ≈ 0.00186/day (Dixon-Coles 1997); tune on your own window.
- **Dixon-Coles ρ (low-score correction):** data-dependent, not universal; fit it (typically small and negative).
- **FDR-band multipliers:** **No rigorously published empirical band→points table exists.** A dedicated search of Fantasy Football Scout, Reddit r/FPL, blogs and academic sources found none. Your reviewer's 1.15→0.85 (bands 2-5) is a defensible monotone heuristic but has no citable evidential basis. Sites quoting specifics (e.g. "Salah 7.2 vs 4.8 pts against weak vs top-six") are unsourced and unreliable. If you want empirical multipliers, derive them from vaastav's archive by joining historical points to official FDR. Otherwise label them explicitly as heuristic priors used only pre-GW4/5.
- **Minutes heuristics / status flags:** community convention is `status='a'`→available; `status='d'` (doubtful) with a `chance_of_playing` percentage → use that percentage; **`status='d'` with no percentage → treat as ~75%**; `status='i'/'s'/'u'` → ~0%. OpenFPL "dispenses with proprietary 'expected minutes' projections, using instead the categorical availability tags provided by the FPL API... 0%, 25%, 50%, 75%, or 100%" and still rivals FPL Review — strong evidence that a simple minutes model is adequate. (OpenFPL's own analysis notes FPL Review's edge on Zeros/Blanks comes precisely from proprietary *start/rest* information the API lacks.)
- **Clean-sheet probability by difficulty:** community tools display ranges roughly 10-58% across the difficulty spectrum. Compute yours directly from the Poisson: P(CS) = P(opponent scores 0) = exp(−λ_opponent).
- **Bonus approximation:** no single published constant; model from BPS or approximate bonus as a monotone function of xGI plus defensive actions, adjusted for the 2026/27 BPS changes (see §7).

### 6. Evaluation practice and achievable accuracy
- **Metrics:** RMSE per player-gameweek (primary in the literature), MAE (secondary), Spearman rank correlation (ranking quality), and captaincy hit-rate.
- **Published benchmarks (OpenFPL paper, prospective on 2024/25 GW32-38):** at the 1-GW horizon, overall RMSE for "Haulers" (≥5 pts) was ~5.14 (OpenFPL) vs ~5.17 (FPL Review) vs ~5.61 (naive "Last 5" baseline). Verbatim: "both OpenFPL and the FPL Review Massive Data Model consistently outperform the baseline method, reducing RMSE by 5-34% across all four return categories." FPL Review wins on low-return players (Zeros/Blanks); OpenFPL wins on high-return players (Tickers/Haulers). A market-data blog (FPL Pulse) claims captain picks averaging "57% more points" than FPL's own xP, but this is self-reported and cross-season, not a controlled comparison — treat as marketing.
- **Naive baseline:** the standard control is "last 5 games mean" (or flat points_per_game). This is what your v1 must beat. The OpenFPL numbers tell you fixture adjustment + minutes modelling buys roughly 5-34% RMSE reduction — meaningful but not enormous, because much of the residual is irreducible football variance.
- **Gameweeks-to-beat-static-FDR:** no rigorous published number found. AIrsenal's own blog documents early-season instability (fitting on few results told it to triple up on defenders who then conceded every week). Practical guidance: keep the FDR-band fallback until ~GW4-6, then blend toward the fitted model based on held-out RMSE.

### 7. Staged recommendation for `domain/projections.py`

**Interface first.** Define one `Projection` value object and a single function `project(player, event) -> Projection` (backing a `(player, event)` table), so the optimiser never sees model internals. Fields: `xp_total`, component parts (`xp_appearance`, `xp_attack`, `xp_cs`, `xp_saves`, `xp_defcon`, `xp_bonus`, `xp_cards`), `p_start`, `xmins`, and a `model_version` tag. Every stage below emits the same object, so beam-search/DP/MILP code is insulated from model changes.

**v1 (shippable this week) — bootstrap-static + fixtures only.**
- Minutes: from `status`/`chance_of_playing` (convention above) + recent starts; derive p60 and p1 from minutes history (last 5 non-zero appearances, per the community xPts convention).
- Attack: `expected_goals_per_90` × (xmins/90) × fixture multiplier × goal points; plus `expected_assists_per_90` × (xmins/90) × fixture multiplier × 3.
- Clean sheet: FDR-band → P(CS) lookup (heuristic), × 4 (GK/DEF) or × 1 (MID); goals-conceded deduction from a banded expected-goals-against.
- DefCon: P(hit threshold)×2 from season-to-date `defensive_contributions` per 90, thresholded at 10 (DEF)/12 (MID/FWD).
- Bonus: simple monotone function of xGI + defensive actions.
- Fixture multiplier: reviewer's 1.15/1.05/1.00/0.90/0.85 by band — **documented in code as heuristic** — with home/away split via γ.
- Failure modes: early-season xG/90 is noisy and missing for new signings; premium-vs-budget separation is weak (the same problem as `ep_next`) until per-90 rates stabilise; DefCon projections rely on a stat with limited early-season history.

**v2 — fitted Dixon-Coles team model on accrued results.**
- Fit α/β/γ/ρ via `scipy.optimize.minimize` on fixtures-endpoint results with time decay ξ=0.00186/day and the τ low-score correction.
- Replace FDR-band P(CS) and goals-conceded with Poisson-derived probabilities; scale attacking multipliers by opponent β/α.
- Use FDR bands only as the pre-GW4/5 fallback and as a regulariser (prior) on newly-promoted teams (Coventry, Ipswich, Hull), seeded from vaastav/FPL-Core-Insights archives.
- Failure modes: instability before ~GW5; identifiability requires a sum constraint; promoted teams need informative priors.

**v3 (optional) — bottom-up xG model from element-summary per-match history.**
- Per-player per-match xG/xA time series → shrink toward position/role priors; better differential detection and minutes modelling.
- This is where you approach OpenFPL/FPL Review territory, at the cost of complexity — only worth it if v2's rank correlation plateaus below your captaincy needs.

**2026/27 rules the projection MUST reflect:**
- **Defensive contributions unchanged** (DEF ≥10 CBIT, MID/FWD ≥12 CBIRT, +2 cap, GKs ineligible). Must be a first-class term.
- **BPS reworked for 2026/27:** players no longer penalised for being tackled; clearances/blocks/interceptions now score 1 BPS per 3 actions (was 1 per 2); GK saves restructured (flat per save + a big-chance-save bonus; penalty save 7 BPS +1 for the big chance). Your bonus approximation should down-weight raw CBI and stop implicitly penalising ball-carrying attackers.
- **Assist definition simplified (from 2025/26, carried into 2026/27):** deflected passes now count if the goalscorer receives in the box with one defensive touch — mildly inflates full-back/crosser xA going forward; historical xA slightly understates future assists.
- **Live-scoring/lockdown changes** (09:00 next-day finalisation; projected bonus after 20 mins) are operational, not projection-relevant.
- **Flag for old repos:** anything assuming populated `strength_attack/defence` fields, or pre-2025/26 scoring without DefCon, is stale against the current API. AIrsenal and vaastav are actively maintained; verify any borrowed coefficient predates the DefCon/BPS-2026 changes before reusing.

## Recommendations
1. **Ship v1 this week** with the full component decomposition behind the `Projection` interface, using per-90 rates × xmins × heuristic fixture multiplier. Benchmark against flat points_per_game on the first few gameweeks' actuals (RMSE + Spearman). This is your control.
2. **Add the Dixon-Coles v2 at ~GW4-6**, blending fitted probabilities in as results accrue and keeping FDR bands as the cold-start fallback. Seed γ≈1.2, ξ=0.00186/day; fit ρ. Trigger the switch when the fitted model's rolling RMSE beats the FDR-band version on held-out gameweeks.
3. **Derive your own FDR-band multipliers** from vaastav's archive at build time if you want defensible numbers; otherwise keep the reviewer's values but tag them `# heuristic, no published empirical basis` in code.
4. **Treat OpenFPL as your evaluation yardstick, not a runtime dependency** — replicate its return-category RMSE breakdown (Zeros/Blanks/Tickers/Haulers) so you know exactly where your model is weak (models tend to be weakest on Zeros, which is a minutes problem).
5. **Only build v3** if v2's rank correlation plateaus below your captaincy needs; the marginal accuracy gain is small relative to complexity.
6. **Benchmark that changes the plan:** if v1 fails to beat the naive baseline by GW6, the bug is almost certainly minutes modelling (the dominant error source for low returns, per OpenFPL), not fixtures — fix `xmins` before adding model complexity.

## Caveats
- **No published FDR-band→points mapping exists.** Any band multipliers are heuristic; sites quoting specific per-band point figures are unsourced. Derive-your-own or label-as-heuristic are the only honest options.
- **Home advantage is declining and volatile** — do not hardcode a single γ; make it fittable and re-estimate through the season. The AIrsenal blog confirms the α/β/γ structure but does not publish a numeric γ, so the ~1.2 seed comes from comparable public Dixon-Coles fits, not from AIrsenal itself.
- **OpenFPL and FPL Form need Understat**, a third-party runtime feed you've excluded. Use them for structure and benchmarks only.
- **FPL Review coefficients are undisclosed** — you can crib philosophy but not numbers.
- **`ep_next` compression, zeroed strength fields, and FDR-as-lookup are current API realities**, consistent with the 2025/26+ field-shape change; do not build any component that depends on the strength fields repopulating.
- **The DefCon and BPS 2026/27 details** come from Premier League official pages and reputable community sites (Fantasy Football Scout, Opta Analyst, Draft Fantasy). The exact BPS conversion constants should be re-verified against `bootstrap-static` `game_settings`/the official rules page before hardcoding.
- **Data caveat:** vaastav's `xP` column may reflect post-match information; do not use it as a pre-deadline feature without shifting it by one gameweek within each player group.
