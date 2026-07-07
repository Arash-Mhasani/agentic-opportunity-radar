# scenarios.feature — Behavior-Driven specification (Day-5: Gherkin, Scenario/Given/When/Then).
# State > Action > Outcome. Each scenario maps to an automated check in tests/ or evals/,
# so the spec and the test suite cannot silently drift apart.

Feature: Opportunity Radar produces safe, constraint-compliant opportunities

  Background:
    Given the founder constraints are solo, <=20 hours/week, low-capital, robotics-only
    And those constraints are enforced in deterministic code, not only in prompts

  Scenario: Reject opportunities that require building hardware or a foundation model
    Given a generated opportunity whose description says "build a new humanoid robot arm"
    When the constraint compliance check scores it
    Then the opportunity is flagged as a violation
    And it is excluded from the ranked output
    # -> tests/test_business_agent.py::test_business_agent_rejects_banned_patterns
    # -> evals/run_evals.py offline check "adversarial_constraint"

  Scenario: Route each source to exactly one analysis skill
    Given a signal with category "paper"
    When the source layer selects a skill
    Then it selects "summarize-academic-paper"
    And an unknown category falls back to "analyze-market-signal"
    # -> evals/run_evals.py offline check "trigger_routing"

  Scenario: Compress sources before synthesis
    Given a raw signal carrying a 50k-token transcript
    When the source skill processes it
    Then only a short structured record is written to the message bus
    And the raw transcript never re-enters the reasoning context
    # -> tests/test_harness.py::test_message_bus_roundtrip_and_compression

  Scenario: Promote foundational signals to evergreen memory
    Given the curation node marks a record as evergreen
    When the cycle completes
    Then that record's signal is stored with is_evergreen = 1
    And it appears in the evergreen context on the next cycle
    # -> tests/test_harness.py::test_evergreen_promotion_round_trip

  Scenario: Bound spend with a Denial-of-Wallet circuit breaker
    Given a per-cycle budget of model calls and USD
    When the budget is exceeded mid-cycle
    Then the circuit breaker trips
    And the cycle freezes with state preserved for forensics
    # -> tests/test_harness.py::test_budget_trips_on_calls / test_budget_trips_on_usd

Feature: Zero-Trust governance on every external tool call

  Scenario: Structural gate blocks a tool the role may not use
    Given the running role is "viewer"
    When the agent attempts to call "notion-create-pages"
    Then the Policy Server denies it at the structural layer
    # -> tests/test_governance.py::test_structural_denies_disallowed_role

  Scenario: Semantic gate blocks an external write that leaks unmasked PII
    Given a write to Notion whose content contains a plain-text email address
    When the Policy Server evaluates the action
    Then it denies it at the semantic layer
    # -> tests/test_governance.py::test_semantic_denies_unmasked_pii

  Scenario: Human-in-the-loop gate guards confirmed writes
    Given an external write tool and no human confirmation
    When the agent attempts the write
    Then the write is blocked until a human approves it
    # -> tests/test_harness.py::test_mcp_write_denied_without_confirmation

  Scenario: Context hygiene resolves placeholders instead of hardcoding secrets
    Given a tool argument containing "[[NOTION_PARENT_PAGE_ID]]"
    When the call is sanitized before execution
    Then the placeholder is replaced from runtime state or the environment
    And no secret or id is hardcoded in any spec, prompt, or test
    # -> tests/test_governance.py::test_context_resolver_resolves_placeholders
