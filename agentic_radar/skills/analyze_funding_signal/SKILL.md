---
name: analyze-funding-signal
description: |
  Parse an open federal funding solicitation (Grants.gov / SBIR / STTR) into a
  non-dilutive funding opportunity: agency, technical deliverable, and closing date.
  Use when a record holds a grant/solicitation description.
  Do NOT use for VC funding news or company press releases (use analyze-market-signal).
version: 1.1.0
allowed-tools: read_bus_record
metadata:
  author: agentic-radar
---

# Analyze Funding Signal

## When to use
- Parsing a federal grant or SBIR/STTR topic description.

## When NOT to use
- Private/VC funding rounds; commercial announcements.

## Workflow
1. Call `read_bus_record` with the record URI.
2. Identify the agency (DOD, NSF, NASA, DOE, ...).
3. Identify the core technical deliverable the government wants.
4. Note the closing/deadline date if present.
5. Emit the record schema, framed as non-dilutive funding. Output only JSON.

## Output format
{"source_type":"grant","title":"[AGENCY] topic","summary":"deliverable in one line",
 "pain_point":"the capability gap the agency is funding, or null",
 "adjacent_transfer": null, "entities":["agency"],
 "evergreen_candidate": false, "url":"...","deadline":"YYYY-MM-DD or null"}

## Anti-patterns to avoid
- Do not recommend pursuing a grant that needs hardware capex the founder can't fund.
