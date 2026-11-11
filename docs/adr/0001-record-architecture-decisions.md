# 1. Record architecture decisions

- Status: accepted
- Date: 2026-11-11

## Context

The 2.0 rewrite makes many decisions whose reasons are not visible in code: why a layer may
import another, why a request is or is not retried, why a licence was chosen. Without a record,
later contributors either re-argue settled questions or reverse them unknowingly.

## Decision

Architecture decisions are recorded as Architecture Decision Records in `docs/adr/`, one file
per decision, named `NNNN-kebab-case-title.md`, using the Nygard format (Status, Context,
Decision, Consequences).

An accepted ADR is never edited in substance. A changed decision gets a new ADR that marks the
old one as `superseded by NNNN`.

ADRs are written when the decision is made, in the same pull request as the code it shapes.

## Consequences

- Reviewers can check a pull request against the decisions it claims to follow.
- The ADR log becomes part of the published documentation in the final stage.
