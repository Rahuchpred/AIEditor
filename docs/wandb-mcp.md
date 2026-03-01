# W&B MCP for AIEdit

Use the W&B MCP server as an analysis layer for prompt tuning and evaluation. It does not replace Mistral or ElevenLabs in this app. The app still generates scripts and audio directly; W&B MCP helps you inspect experiment data, compare prompt versions, and review quality signals.

## Current Status

This machine already has a global Codex MCP entry for W&B:

- Server name: `wandb`
- URL: `https://mcp.withwandb.com/mcp`
- Auth mode: bearer token from `WANDB_API_KEY`

The server is not usable until `WANDB_API_KEY` is present in the Codex environment.

## Activate It

1. Set a W&B API key in the environment used by Codex.
2. Restart Codex if you changed the environment after launching it.
3. Verify the server is registered:
   - `codex mcp list`
4. Once `WANDB_API_KEY` is set, Codex can query the W&B MCP server.

If `WANDB_API_KEY` is missing, Codex reports:

- `Environment variable WANDB_API_KEY for MCP server 'wandb' is not set`

## What It Helps With

For AIEdit, the best use is prompt and output analysis:

- compare prompt template versions for reel generation
- inspect which prompt variants cause more script regenerations
- track which outputs feel "AI" versus "human"
- compare hook and personality presets once those controls exist
- review prompt/output traces across manual testing sessions
- summarize evaluation results into W&B reports

This is especially useful before and after prompt changes in:

- `app/reel_prompts.py`
- `app/prompts.py`

## Recommended Prompt-Eval Data To Track

The app does not currently log prompt traces to W&B/Weave. To get the most value from the MCP server later, treat each script-generation attempt as an evaluation record and capture:

- prompt version id
- rough idea input
- selected hook style
- selected personality style
- clip count
- generated hook
- generated body segments
- generated CTA
- generated `full_narration`
- whether the user regenerated the script
- whether the user edited the generated text
- whether voiceover generation succeeded
- whether reel assembly succeeded
- a manual quality label such as `sounds_human`, `too_generic`, or `strong_hook`

Without this data, W&B MCP is still available, but it has much less value for this project.

## How To Use It In Practice

After W&B data exists, use Codex to ask natural-language questions against the `wandb` MCP server, for example:

- "Show the latest prompt-eval runs for the AIEdit project."
- "Compare script regeneration rate by prompt version."
- "Which hook style produces the fewest rewrites?"
- "Find runs tagged `too_generic` and summarize repeated wording patterns."
- "Create a short report comparing personality presets by acceptance rate."

The server supports W&B data access such as:

- querying runs and projects
- querying Weave traces and evaluations
- counting trace usage
- creating W&B reports

## How This Fits The App

Use this workflow:

1. Change prompt design in `app/reel_prompts.py`.
2. Run prompt evaluations and collect outputs.
3. Log the results into W&B/Weave.
4. Use W&B MCP from Codex to compare versions and identify better-performing prompt structures.
5. Keep only prompt changes that improve real outcomes, not just subjective feel.

This keeps prompt iteration measurable instead of purely intuitive.

## Limits

- W&B MCP does not generate better prompts by itself.
- W&B MCP does not rewrite your Mistral requests automatically.
- W&B MCP is not part of the FastAPI runtime path.
- W&B MCP only helps if evaluation data is logged to W&B/Weave.
