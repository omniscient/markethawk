# Dark Factory vs. Agyn: Structured Comparison

**Date**: 2026-06-04
**Issue**: [#184](https://github.com/omniscient/markethawk/issues/184)
**Reference**: Benkovich & Valkov, "Agyn: A Multi-Agent System for Team-Based Autonomous Software Engineering", arXiv:2602.01465v2

---

## Executive Summary

<!-- FILL: 3–5 sentence synthesis after Tasks 2–4 are complete -->

---

## Alignment Matrix

| # | Dimension | Dark Factory | Agyn | Alignment |
|---|-----------|-------------|------|-----------|
| 1 | Agent topology | | | |
| 2 | Coordination / communication | | | |
| 3 | Task ingestion | | | |
| 4 | Isolation & infrastructure | | | |
| 5 | Verification / quality gates | | | |
| 6 | Evaluation / benchmarking | | | |
| 7 | Resumability & statelessness | | | |

Alignment key: **Aligned** / **Partial** / **Differs** / **Gap** (we lack) / **Advantage** (we lead)

---

## Dimension Analysis

### 1. Agent Topology

**Dark Factory:**
<!-- FILL: how many agents, roles, concurrency model, pipeline structure -->

**Agyn:**
<!-- FILL: team/role model, concurrency, specialization -->

**Comparison:**
<!-- FILL: where they converge, where they diverge -->

---

### 2. Coordination / Communication

**Dark Factory:**
<!-- FILL: how state flows between stages (GitHub branch, issue comments, reconstruct-from-branch) -->

**Agyn:**
<!-- FILL: inter-agent communication semantics, message passing, shared state -->

**Comparison:**
<!-- FILL -->

---

### 3. Task Ingestion

**Dark Factory:**
<!-- FILL: GitHub Issues + backlog scheduler (scheduler.sh), label-based dispatch, WIP limit -->

**Agyn:**
<!-- FILL: Agyn's task intake mechanism -->

**Comparison:**
<!-- FILL -->

---

### 4. Isolation & Infrastructure

**Dark Factory:**
<!-- FILL: ephemeral --rm container, docker-socket-proxy, per-issue mh-preview-* stacks, port scheme -->

**Agyn:**
<!-- FILL: Agyn's infra/resource management, isolation model -->

**Comparison:**
<!-- FILL -->

---

### 5. Verification / Quality Gates

**Dark Factory:**
<!-- FILL: conformance stage, validate stage, CI-failure gate, spec-fidelity checks -->

**Agyn:**
<!-- FILL: evaluation/repair loop, review agents, quality mechanisms -->

**Comparison:**
<!-- FILL -->

---

### 6. Evaluation / Benchmarking

**Dark Factory:**
<!-- FILL: current state — no quantitative benchmark -->

**Agyn:**
<!-- FILL: SWEBench results, comparison vs SWE-Agent / OpenHands / miniSWEAgent -->

**Comparison:**
<!-- FILL -->

---

### 7. Resumability & Statelessness

**Dark Factory:**
<!-- FILL: "Continue issue #N" reconstruct-from-branch, stateless container, GitHub as durable state -->

**Agyn:**
<!-- FILL: Agyn's approach to interrupted/resumed tasks -->

**Comparison:**
<!-- FILL -->

---

## Notable Gaps

<!-- FILL: G1, G2, ... — each gap with Severity and Context -->

---

## Prioritized Improvements (Agyn-Inspired)

<!-- FILL: P1, P2, ... — each improvement with Priority, Effort, and Source dimension -->
