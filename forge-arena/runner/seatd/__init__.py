"""seatd — autonomous per-seat brains for the Forge interactive arena.

Transport mandate: seats run on the Claude Max subscription via the Claude
Agent SDK / headless claude (see docs/AGENT-SDK-SEATS.md). The runner performs
ALL file I/O itself; the model is a pure text reasoner with no tools.
"""
