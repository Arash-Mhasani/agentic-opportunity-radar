---
name: analyze-market-signal
description: |
  Extract the business model, funding amount, or product-launch detail from a broad
  market signal (HackerNews launch, RSS tech news, VC funding announcement, startup).
  Use as the default for non-academic, non-grant, non-job records.
  Do NOT use for paper abstracts (use summarize-academic-paper).
version: 1.1.0
allowed-tools: read_bus_record
metadata:
  author: agentic-radar
---

# Analyze Market Signal

## When to use
- HackerNews discussions, TechCrunch/Substack items, funding announcements, YC startups.

## When NOT to use
- Academic papers; federal grants; raw job posts.

## Workflow
1. Call `read_bus_record` with the record URI.
2. Identify the company/product/trend; if a funding round, capture amount + investors.
3. Decide whether it is a competitive threat or an opening for a solo wedge.
4. Emit the record schema. Output only JSON.

## Output format
{"source_type":"market","title":"...","summary":"threat or opening in one line",
 "pain_point":"the unmet need, or null","adjacent_transfer": null,
 "entities":["company/investors"], "evergreen_candidate": true/false, "url":"..."}

## Anti-patterns to avoid
- Do not mark routine fundraising news evergreen; reserve evergreen for durable facts
  (a platform becoming standard, a lasting category shift).
