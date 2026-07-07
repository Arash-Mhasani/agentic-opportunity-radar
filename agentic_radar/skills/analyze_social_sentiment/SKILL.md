---
name: analyze-social-sentiment
description: |
  Identify recurring complaints, named bottlenecks, or shifts in focus among deep-tech
  robotics researchers from fragmented social posts (X/Twitter, Substack notes). Use
  when a record holds short social posts and you want the community's pain signal.
  Do NOT use for customer-support tickets or consumer marketing sentiment.
version: 1.1.0
allowed-tools: read_bus_record
metadata:
  author: agentic-radar
---

# Analyze Social Sentiment

## When to use
- A record holds posts from robotics/AI researchers or builders.
- You want recurring complaints or a sudden shift in what people are working on.

## When NOT to use
- Long-form articles (use summarize-academic-paper).
- Consumer/brand sentiment unrelated to the robotics stack.

## Workflow
1. Call `read_bus_record` with the record URI.
2. Cluster the posts by theme; ignore one-off jokes and bot spam.
3. Surface any recurring bottleneck or a notable shift in focus.
4. Emit the record schema. Output only the JSON object.

## Output format
{"source_type":"social","title":"theme","summary":"the recurring signal",
 "pain_point":"the named bottleneck, or null", "adjacent_transfer": null,
 "entities":["handles/orgs"], "evergreen_candidate": false, "url":"..."}

## Anti-patterns to avoid
- Do not over-read a single post as a trend; require recurrence.
