#!/usr/bin/env bash
# Regenerate the committed demo output. CI runs this and fails if anything differs.
# Offline: frameworks run for real, the model is simulated, no credentials are used.
set -euo pipefail
cd "$(dirname "$0")/../.."
out=examples/architecture/sample_output
python -m examples.architecture.run_demo --framework openai-agents --scenario investigate --handoff > "$out/openai-agents.txt"
python -m examples.architecture.run_demo --framework llamaindex --scenario investigate > "$out/llamaindex.txt"
python -m examples.architecture.run_demo --framework all --scenario all --brief > "$out/all-scenarios-brief.txt"
