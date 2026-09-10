"""Provider pricing, kept separate from evaluation/cases.json and runner.py so a
price update never requires touching or rerunning the clinical evaluation data.

Figures are approximate list prices (USD per 1,000 tokens) as of this codebase's
knowledge cutoff and WILL drift — treat cost figures in any report as rough
prototype estimates, not a billing-accurate number. Update the values below (or
override at the CLI with --input-price-per-1k / --output-price-per-1k) before
trusting a cost report for anything beyond ballpark sizing.
"""

PRICING_PER_1K_TOKENS: dict[str, dict[str, dict[str, float]]] = {
    "openai": {
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "gpt-4o": {"input": 0.0025, "output": 0.01},
        # UNCONFIRMED — no verified published price for this model was available
        # when this file was written; placeholder set to the same order of
        # magnitude as gpt-4o-mini given both are positioned as low-cost mini
        # tiers. Replace with the real published rate before trusting any cost
        # figure computed against this model.
        "gpt-5-mini": {"input": 0.00015, "output": 0.0006},
    },
    "anthropic": {
        "claude-sonnet-5": {"input": 0.003, "output": 0.015},
        "claude-haiku-4.5": {"input": 0.001, "output": 0.005},
    },
}


def estimate_cost_usd(provider: str, model: str, input_tokens: int, output_tokens: int) -> float | None:
    if provider == "ollama":
        # $0 API cost by definition — but this is NOT free: local compute/
        # hardware (and its power draw, and the RAM/disk it occupies) is a real
        # cost the report must not imply away. See report.py's cost section.
        return 0.0
    table = PRICING_PER_1K_TOKENS.get(provider, {}).get(model)
    if table is None:
        return None
    return (input_tokens / 1000) * table["input"] + (output_tokens / 1000) * table["output"]
