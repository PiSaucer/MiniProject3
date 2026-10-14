# Disagreement — asaucer & bslessma

## Example 1: IntelOwl (HasRecovered)

* **WOCProjectID:** [https://github.com/intelowlproject/IntelOwl](https://github.com/intelowlproject/IntelOwl)
* **Parties for discussion:** `bslessma` (original author) and `asaucer` (validator)
* **Field:** `HasRecovered`
* **Author value (`bslessma`):** Yes
* **Validator value (`asaucer`):** No
* **Pre-discussion agreement:** No

**Evidence and reason for disagreement.** The partner's project statistics report **LongestGapLength = 0 months**, and the gap-commit file contains no recovery boundary. Without an identified inactivity gap, continued activity is not evidence that the project recovered *from a gap*. This is a disagreement about what qualifies as recovery, not whether the repository is active.

**Final adjudicated value:** `No`.

**Evidence rationale.** There is no qualifying gap to recover from. If the coding guide instead allows “recovered” to mean simply “active,” we need to the final value follows the agreed coding-guide interpretation.

**Actual discussion outcome:** Confirmed by both partners. Both partners agreed with this adjudicated value and resolution type; the resolution CSV records post-discussion agreement.

## Example 2: mve (WhyRecovered)

* **WOCProjectID:** [https://github.com/simonfuhrmann/mve](https://github.com/simonfuhrmann/mve)
* **Parties for discussion:** `bslessma` (original author) and `asaucer` (validator)
* **Field:** `WhyRecovered`
* **Author value (`bslessma`):** Feature implementation
* **Validator value (`asaucer`):** Compatibility fixes and CI/build maintenance (trigger not established)
* **Pre-discussion agreement:** No

**Evidence and reason for disagreement.** The recorded **24-month gap (May 2022–April 2024)** ends with compatibility-related commits rather than clear new feature implementation. Commit `3d18f380a` (2024-05-09) guards SSE headers to compile on CPUs without SSE2/3; `d9a273a25` (2024-05-10) continues the same fix. These commits establish *what work resumed*, but not the developers' personal motivation for returning.

**Final adjudicated value:** `Compatibility fixes and CI/build maintenance (trigger not established)`.

**Evidence rationale.** Describe the post-gap changes supported by the commit messages, without claiming an underlying cause that the traces do not establish.

**Actual discussion outcome:** Confirmed by both partners. Both partners agreed with this adjudicated value and resolution type; the resolution CSV records post-discussion agreement.

## Example 3: hyperhdg (ActivityPattern)

* **WOCProjectID:** [https://github.com/AndreasRupp/hyperhdg](https://github.com/AndreasRupp/hyperhdg)
* **Parties for discussion:** `bslessma` (original author) and `asaucer` (validator)
* **Field:** `ActivityPattern`
* **Author value (`bslessma`):** declining
* **Validator value (`asaucer`):** U-shaped
* **Pre-discussion agreement:** No

**Evidence and reason for disagreement.** The timeline has a large initial period followed by very low activity and later a rebound. The four quarter-period means are **89.1 → 11.8 → 2.1 → 15.5 commits/month**. The annual totals also move from **0 commits in 2023** to **86 in 2024** and **228 in 2025**. The early period is much stronger than the rebound, so it is not a symmetric U, but calling the overall history only “declining” ignores the later return of activity.

**Final adjudicated value:** `U-shaped`.

**Evidence rationale.** The broad pattern is high → low → higher again; the final value follows the Coding Guide interpretation of this asymmetric rebound as U-shaped.

**Actual discussion outcome:** Confirmed by both partners. Both partners agreed with this adjudicated value and resolution type; the resolution CSV records post-discussion agreement.

## Example 4: alliancedb (Currentstatus)

* **WOCProjectID:** [https://github.com/intellistream/alliancedb](https://github.com/intellistream/alliancedb)
* **Parties for discussion:** `bslessma` (original author) and `asaucer` (validator)
* **Field:** `Currentstatus`
* **Author value (`bslessma`):** Active
* **Validator value (`asaucer`):** Inactive
* **Pre-discussion agreement:** No

**Evidence and reason for disagreement.** The validation log explicitly uses the **historical cutoff of September 30, 2025**, with a project considered Active only if it has a commit dated **April 1–September 30, 2025**. The latest qualifying historical commit for AllianceDB was `fbf471df3dfa`, dated **March 19, 2025**, before the active window. That means this label is about status at the assignment's cutoff, not whether the repository received any commits later in 2026.

**Final adjudicated value:** `Inactive`.

**Evidence rationale.** The March 19, 2025 commit falls outside the stated six-month activity window for the historical cutoff.

**Actual discussion outcome:** Confirmed by both partners. Both partners agreed with this adjudicated value and resolution type; the resolution CSV records post-discussion agreement.

**Supporting commit link:** [March 19, 2025 README update](https://github.com/DataSysResearch/AllianceDB/commit/fbf471df3dfaa817a50f7abdcfa565efb19626de).

## Example 5: grr (RecentThemes)

* **WOCProjectID:** [https://github.com/google/grr](https://github.com/google/grr)
* **Parties for discussion:** `bslessma` (original author) and `asaucer` (validator)
* **Field:** `RecentThemes`
* **Author value (`bslessma`):** Bug Fixes
* **Validator value (`asaucer`):** Security patches:Other (CI/workflow maintenance)
* **Pre-discussion agreement:** No

**Evidence and reason for disagreement.** In the review of the **10 most recent commits as of October 12, 2026**, commit `d71034ae4` fixes an IDOR vulnerability and commit `9f8f7974b` hardens file-blob access validation. Those are more specifically *security patches* than generic bug fixes. The validator's breakdown is **Other: 4, Security patches: 3, Feature development: 1, Bug fixes: 1, Release: 1**, with some of the Other commits involving workflow or CI maintenance. This explains why the author's single label, Bug Fixes, may be too broad.

**Final adjudicated value:** `Security patches:Other (CI/workflow maintenance)`.

**Evidence rationale.** Use the more specific security label and the observed CI/workflow activity while acknowledging that some security patches are also bug fixes in a broader sense.

**Actual discussion outcome:** Confirmed by both partners. Both partners agreed with this adjudicated value and resolution type; the resolution CSV records post-discussion agreement.

**Supporting history:** [GRR commits](https://github.com/google/grr/commits).
