# Cursor + Meterless development instructions
Use Cursor to extend the working ENIGMA MVP. Read `.cursor/rules/enigma.mdc`.
For the Meterless World Model implementation, review upstream `https://github.com/Meterless/World-Model` and follow its `AGENTS.md` and conformance guidance. This MVP has persisted event-sourced case facts but does not claim full implementation/conformance with Meterless World Model reference specification.
Tasks to complete in Cursor: implement canonical stable entity IDs, derived latest state view, change versioning, context builder, lineage and conformance tests. Keep audit events and risk gates.
NVIDIA: configure a Nemotron lane in Meterless Nightshift, set model ID, exercise the live endpoint, capture redacted request trace.
Zetaris: create accessible SQL sources, configure adapter views, inspect live response shape, and validate normalization with tests.
