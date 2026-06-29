#!/usr/bin/env bash
# Agent role-ID constants for Dark Factory memory scoping.
# Sourced by gate_lib.sh and by each phase command that writes or reads memory.
# Do NOT add set -euo pipefail — this file is sourced and must not alter caller shell options.

MEMORY_PROJECT="markethawk"

AGENT_ID_FACTORY_DIRECTOR="factory-director"
AGENT_ID_INTAKE_TRIAGE="intake-triage-agent"
AGENT_ID_REFINEMENT="refinement-agent"
AGENT_ID_PLANNING="planning-agent"
AGENT_ID_IMPLEMENTATION="implementation-agent"
AGENT_ID_VALIDATION="validation-agent"
AGENT_ID_CODE_REVIEW="code-review-agent"
AGENT_ID_SECURITY="security-agent"
AGENT_ID_DECONFLICT="deconflict-agent"
AGENT_ID_CI_RESCUE="ci-rescue-agent"
AGENT_ID_MERGE_GATE="merge-gate-agent"
AGENT_ID_COST_TELEMETRY="cost-telemetry-agent"
AGENT_ID_HUMAN_LIAISON="human-liaison-agent"
