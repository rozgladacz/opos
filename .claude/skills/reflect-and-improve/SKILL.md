Analyze the last 10 Claude Code session transcripts for this project and produce a friction report with actionable improvements:

1. Run: `python scripts/reflect_and_improve.py --sessions 10 --out FRICTION_REPORT.md`
2. Read FRICTION_REPORT.md and summarize the top 3 friction categories with hit counts.
3. For each category with >5 hits, propose a concrete addition to AGENTS.md or Makefile.
4. Apply the approved changes directly (AGENTS.md, Makefile, inline comments).
5. Create a draft PR titled "docs: friction-driven improvements YYYY-MM-DD" with FRICTION_REPORT.md attached as context.

Friction categories tracked: encoding/smart-quotes, tests skipped, git errors, bash errors, regressions, user corrections, layer misses, session context loss.

Metrics are appended to the table in section 5 of FRICTION_REPORT.md on each run — use this to track improvement over time.
