# ─────────────────────────────────────────────────────────────────────────────
# PersonaPlex LiveKit Agent — Docker Image
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    ffmpeg \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Working directory
WORKDIR /app

# Install Python dependencies first (layer cache)
COPY requirements_personaplex.txt .
RUN pip install --no-cache-dir -r requirements_personaplex.txt
RUN pip install --no-cache-dir scipy sphn

# Copy project source
COPY src/ ./src/
COPY personaplex_agent_new.py .
COPY token_server.py .
COPY .env .

# Expose token server port
EXPOSE 8080

# Default: run the agent
# Override with: docker-compose run agent python token_server.py
CMD ["python", "personaplex_agent_new.py", "--room", "personaplex-test"]