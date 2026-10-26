"""AI agent package.

The agent is intentionally small and bounded: one model, a whitelist of
read-only tools, hard limits on rounds and tool calls, and server-side
validation of everything the model returns.
"""
