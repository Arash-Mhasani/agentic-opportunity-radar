---
name: analyze-job-signal
description: |
  Read a robotics job posting (Adzuna / Greenhouse career page) and infer the talent
  gap and the bottleneck the company is hiring to solve. Use when a record holds a job
  description and you want the implied market demand.
  Do NOT use for paper abstracts or funding solicitations.
version: 1.1.0
allowed-tools: read_bus_record
metadata:
  author: agentic-radar
---

# Analyze Job Signal

## When to use
- Parsing an Adzuna posting or a company Greenhouse role.

## When NOT to use
- Academic or funding content.

## Workflow
1. Call `read_bus_record` with the record URI.
2. Extract the specific technical skills required (Isaac Sim, CUDA, ROS2, tactile, ...).
3. Infer the bottleneck the company is trying to solve by hiring this role.
4. Emit the record schema. Output only JSON.

## Output format
{"source_type":"job","title":"[Company] Role","summary":"the implied demand",
 "pain_point":"the bottleneck this hire addresses, or null","adjacent_transfer": null,
 "entities":["company"], "evergreen_candidate": false, "url":"..."}

## Anti-patterns to avoid
- A single generic posting is weak signal; emphasize specific, unusual skill demands.
