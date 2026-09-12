# Roadmap

1. **v0.1 validation:** run credentialed Austrian price/load/generation/flow checks,
   record observed coverage and resolve any real provider-series ambiguities.
   Confirm primary-owner reuse conditions and select a software license.
2. **v0.2:** extend verified German/neighbor coverage, add SMARD, persist historical
   observations and revisions, and add explicit energy-conserving resampling.
3. **v0.3:** add forecast primitives, outages and balancing datasets with provenance.
4. **v0.4:** expose the existing application service through a thin MCP adapter,
   then webhooks and event detection without duplicating calculations.
5. **v0.5:** build a dashboard over the normalized REST API.
6. **Later:** forecast APIs, flexibility intelligence and enterprise/private deployment.

A future Grid Stress methodology would need load, residual load, available
production, imports, interconnector flows, outages, price volatility, balancing
activation and reserve conditions. Each input needs explicit coverage, timing,
quality and revision rules. Define an operational target, validate against
historical events, evaluate uncertainty and benchmark simple baselines before
publishing a score. No arbitrary weighted score exists in v0.1.
