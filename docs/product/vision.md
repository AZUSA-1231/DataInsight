# Product Vision

## Problem

Raw-data analysis is a coupled workflow: users must understand data quality,
translate a business question into analytical operations, choose suitable
methods, run code, diagnose failures, and communicate limitations. Generic chat
tools often skip these boundaries and produce plausible-looking conclusions
without a defensible execution trail.

## Product

DataInsight is a local analysis workspace for people who understand their
business domain but do not want to author a complete Python pipeline. It gives
the user and the agent a shared Plan that can be inspected, edited, executed,
and partially rerun.

The product promise is not one-click magic. It is a trustworthy path from data
and intent to reproducible evidence:

```text
inspect data -> understand intent -> review plan -> execute units -> retain results
```

## Principles

- Data facts come from deterministic inspection, not LLM invention.
- The workspace Plan is visible and editable before execution.
- Every unit declares the fields it reads and the data shape it may produce.
- Reports disclose what the available data cannot answer.
- An analysis should run once and remain viewable across restarts.
- Templates cover repeatable operations; generated functions cover constrained
  custom logic; open-ended artifact generation remains isolated.

## Current Users

The current product is optimized for its developer and other trusted local
users. Multi-user permissions, hosted untrusted execution, live databases, and
collaboration are outside the current boundary.

## Success Direction

Future cycles should improve measurable user outcomes: first-run completion,
time to a useful finding, clarity of plan intervention, rerun consistency, and
honesty of data-business alignment. Feature count is not a success metric.
