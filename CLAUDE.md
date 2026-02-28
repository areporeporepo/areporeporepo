# CLAUDE.md

## Project Overview

Personal health tracking and AI agent system focused on Zone 5 cardiovascular training. Combines Apple Watch heart rate data with GitHub-style contribution visualizations, deployed as Vercel serverless functions.

## Architecture

- `api/` — Vercel serverless functions (Node.js)
  - `zone5-contributions.js` — SVG contribution graph generator
  - `health-sync.js` — iOS health data sync endpoint
- `scripts/` — Data processing utilities (Python)
- `.github/workflows/` — 10 GitHub Actions workflows for automated updates, AI agents, and data collection
- `.github/scripts/` — Python scripts for GitHub Actions (agent, weather, tracking, etc.)

## Key Commands

- `node test-api.js` — Run local API test (generates test-output.svg)
- `npm run deploy` — Deploy to Vercel (`vercel --prod`)
- `python3 scripts/parse-apple-health.py <export.xml>` — Parse Apple Health data

## Zone 5 Config

- User age: 30
- Zone 5 range: 171–190 bpm (90–100% max HR)
- Daily goal: 15+ minutes in Zone 5

## Dependencies

- **Node.js**: vercel (dev only), no runtime deps
- **Python**: requests, pyyaml (for GitHub scripts)

## Notes

- Deployed on Vercel as serverless functions (1024 MB memory, 10s max duration)
- `zone5-data.json` is the live data file committed to git
- GitHub Actions workflows run on various schedules (some every 5 minutes)
