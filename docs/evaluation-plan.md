# Evaluation Set

Use a fixed manual evaluation pack before release:

- 5 English samples with clear speech
- 5 non-English samples that should become English outputs
- 5 noisy or filler-heavy samples
- 5 short style-control samples that cover both preset and custom styles

For each sample, verify:

- The transcript is captured without provider errors
- Corrected captions preserve meaning
- The rewrite is a single English string
- Exactly three speaking tips are returned
- Timestamps are preserved when enabled

## Prompt Evaluation With W&B MCP

Use W&B MCP as the analysis layer for prompt experiments, especially for reel-script quality:

- version each prompt change
- record the prompt inputs and outputs
- tag outputs that sound generic, repetitive, or strong
- compare regeneration rate and manual edits across prompt versions

Project usage notes are in [docs/wandb-mcp.md](/Users/rahazh/Documents/coding/AIEdit/docs/wandb-mcp.md).
