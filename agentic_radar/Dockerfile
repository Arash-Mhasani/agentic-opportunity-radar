# Sandboxed execution for the Opportunity Radar (Day-5: "Sandboxing").
#
# Runs the agent in an ephemeral, low-privilege container — a contained "blast radius"
# so a tricked tool call cannot touch the host. Node is included only because the
# consumed MCP servers (Notion, yt-mcp) launch via `npx`.
#
# Build:  docker build -t opportunity-radar .
# Run a single cycle (mount your .env, never bake secrets into the image):
#   docker run --rm --env-file .env \
#     --read-only --tmpfs /tmp --cap-drop ALL \
#     -v "$PWD/agentic_radar/memory:/app/agentic_radar/memory" \
#     opportunity-radar
FROM python:3.12-slim

# Node for npx-launched MCP servers
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY agentic_radar/requirements.txt /app/agentic_radar/requirements.txt
RUN pip install --no-cache-dir -r /app/agentic_radar/requirements.txt

COPY agentic_radar /app/agentic_radar

# Drop privileges: run as a non-root user (least privilege).
RUN useradd --create-home --uid 10001 radar && chown -R radar:radar /app
USER radar

ENV PYTHONUNBUFFERED=1 RADAR_ENV=production
# Default: one pipeline cycle. Override CMD for the dashboard or evals.
CMD ["python", "agentic_radar/core/orchestrator.py"]
