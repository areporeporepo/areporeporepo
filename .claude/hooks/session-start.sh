#!/bin/bash
set -euo pipefail

# Only run in remote (Claude Code on the web) environments
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Install Node.js dependencies
cd "$CLAUDE_PROJECT_DIR"
npm install

# Install Python dependencies used by scripts
pip install requests pyyaml
