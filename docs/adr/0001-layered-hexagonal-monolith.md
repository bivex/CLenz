# ADR 0001: Start with a layered hexagonal monolith

## Status

Accepted

## Context

The system is greenfield. The team needs clean boundaries, fast iteration, and easy onboarding more than distributed deployment.

## Decision

Build a monolith with explicit domain, application, infrastructure, and presentation layers. Use ports and adapters so infrastructure remains replaceable.

## Consequences

Positive:

* simple deployment
* high testability
* clear dependency rules
* easy future extraction of bounded contexts if warranted

Negative:

* one deployable unit
* strong discipline is required to keep boundaries clean

