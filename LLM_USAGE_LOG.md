# LLM Usage Log

**Tool / Model:** Claude (claude.ai), Claude Opus 5.5

| Date | Purpose | What the LLM produced | What we did | Result |
|---|---|---|---|---|
| 2026-09-28 | Rule analysis and code review | Summary of strategically relevant rules; review of our flag-movement code (identified stacks all chasing one target) | Reviewed; fix in progress in our pathing module | Pending |
| 2026-09-28 | Local testing setup | `arena.py`: batch runner on the official engine, plays each map from both sides and reports win rate | Ran locally; added Windows compatibility | Working |
| 2026-09-28 | Baseline measurement | 60-game test: flags-only bot vs `example_lv2` | Reproduced locally | 0% win rate; lost by elimination. Priority changed to warrior/defence logic |

## Prompts (summary)
- Asked for a review of the starter kit, rulebook and our current code, and for the next highest-value task.
- Asked for a tool to test bots locally over many matches.
