---
name: summarize-academic-paper
description: |
  Extract the core method, math, and benchmark results from a dense academic paper
  (arXiv / ICRA / CoRL). Use when a record contains a paper abstract or full text and
  you need the technical breakthrough distilled into a structured record.
  Do NOT use for news articles, blog posts, or marketing pages (use
  analyze-market-signal instead).
version: 1.1.0
allowed-tools: read_bus_record read_reference
metadata:
  author: agentic-radar
---

# Summarize Academic Paper

## When to use
- A record holds an arXiv/ICRA/CoRL abstract or paper text.
- You need the core architecture, the key equation/insight, and the datasets used.

## When NOT to use
- Non-academic content (news, blogs, funding press releases).
- Pure benchmark leaderboards with no method described.

## Workflow
1. Call `read_bus_record` with the record URI.
2. Identify the single core methodological or architectural contribution.
3. Identify the datasets / benchmarks and the headline result number.
4. Decide whether this is a transferable technique for a robotics wedge (a method
   from an adjacent field — vision, NLP, synthetic data — that could solve a
   robotics bottleneck). If unsure about cross-domain transfer, call
   `read_reference` with name `cross_domain_transfer.md`.
5. Emit the record schema in Output format. Output only the JSON object.

## Output format
{"source_type":"paper","title":"...","summary":"1-2 sentences, technical",
 "pain_point": "the robotics bottleneck this could address, or null",
 "adjacent_transfer":"the transferable technique, or null",
 "entities":["lab/author/org names"], "evergreen_candidate": true/false, "url":"..."}

## Examples
- Input: "We introduce a diffusion policy that ..." → Output: pain_point about
  multimodal action prediction, adjacent_transfer "diffusion models → manipulation".

## Anti-patterns to avoid
- Do not summarize the abstract verbatim; state the contribution in your own words.
- Do not set evergreen_candidate=true for incremental results; reserve it for
  canonical methods/benchmarks that stay referenced for months.
