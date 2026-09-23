# FlytBase BDR Intelligence Agent

Evidence-first multi-agent outbound system for mining accounts in Latin America.

## What runs

- FastAPI website and evidence store
- n8n master orchestrator
- 8 specialized agents (ICP, discovery, account verification, contact discovery, contact verification, research, personalization, fact-check)
- 3 tool workflows (search, page fetch, LLM)

## One-click Render deployment

1. Push this repository to GitHub.
2. In Render, select **New → Blueprint** and choose the repository.
3. Render reads `render.yaml` and asks for secret environment variables.
4. Set `OPENAI_API_KEY` to a fresh Atria API key.
5. Optionally set one of `BRAVE_API_KEY`, `SERPER_API_KEY`, or `TAVILY_API_KEY` for better contact discovery.
6. Deploy the Blueprint.

The Blueprint creates one Docker web service in Singapore with a 1 GB persistent disk. FastAPI is public; n8n stays private inside the container. The website calls the internal n8n webhook.

> The persistent disk requires a paid Render Starter service. For a free non-persistent demo, change `plan: free` and remove the `disk:` block, but runs and n8n state reset on redeploy/restart.

## Local run

```bash
cp .env.example .env
# Add OPENAI_API_KEY
bash bootstrap.sh
```

Open `http://localhost:8000`.

## Security

Never commit `.env`. API keys are configured using Render secret environment variables (`sync: false` in `render.yaml`). Rotate any key pasted into chat before public deployment.

See [`docs/Submission.md`](docs/Submission.md) for architecture, design decisions, failure log, and walkthrough.
