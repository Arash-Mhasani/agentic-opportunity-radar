---
name: analyze-youtube-transcript
description: |
  Extract explicit technical pain points, bottlenecks, or robotics breakthroughs from
  a noisy auto-generated YouTube transcript (talk, demo, product launch). Use when a
  record contains transcript text and you need the engineering signal, not the hype.
  Do NOT use for entertainment, vlogs, or general marketing videos.
version: 1.1.0
allowed-tools: read_bus_record
metadata:
  author: agentic-radar
---

# Analyze YouTube Transcript

## When to use
- A record holds a transcript from a robotics/AI talk, demo, or launch.
- You need the bottlenecks the speaker names out loud.

## When NOT to use
- Entertainment or non-technical content.
- Long-form written articles (use summarize-academic-paper or analyze-market-signal).

## Workflow
1. Call `read_bus_record` with the record URI.
2. Skip intros, outros, sponsor reads, and marketing fluff.
3. Extract explicit pain points / bottlenecks the speaker states ("the hard part is
   ...", "we still struggle with ...").
4. Note any proposed solution or workaround they mention.
5. Emit the record schema. Output only the JSON object.

## Output format
{"source_type":"video","title":"...","summary":"the bottleneck + any proposed fix",
 "pain_point":"the specific technical challenge, or null",
 "adjacent_transfer": null, "entities":["company/speaker"],
 "evergreen_candidate": false, "url":"..."}

## Anti-patterns to avoid
- Do not treat speaker enthusiasm as a bottleneck; only quote stated problems.
- Do not invent metrics that are not in the transcript.
