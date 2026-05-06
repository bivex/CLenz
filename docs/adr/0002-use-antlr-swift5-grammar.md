# ADR 0002: Use the public ANTLR Swift 5 grammar as the initial parsing engine

## Status

Accepted

## Context

The business needs a working Swift parser without building a grammar from scratch. The public `antlr/grammars-v4` repository provides a maintained Swift grammar.

## Decision

Use `antlr/grammars-v4/swift/swift5` as the initial grammar source and generate a Python parser through ANTLR 4.13.2 with a reproducible compatibility patch step for Python target generation.

## Consequences

Positive:

* faster delivery
* transparent source of truth
* easier future grammar updates
* compatibility fixes stay scripted instead of becoming undocumented manual edits

Negative:

* grammar README states known limitations and Swift 5.4 targeting
* behavior can diverge from the Swift compiler
* Python target generation is not plug-and-play because upstream support code is Java-oriented
* downstream consumers must treat grammar version as an explicit compatibility concern
