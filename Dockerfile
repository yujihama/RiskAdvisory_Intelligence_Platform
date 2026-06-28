FROM python:3.13-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY data/clients ./data/clients
COPY data/expert_knowledge ./data/expert_knowledge

RUN python -m pip install --no-cache-dir -e .

CMD ["python", "-m", "risk_agent_platform.run_scenario", "--help"]
