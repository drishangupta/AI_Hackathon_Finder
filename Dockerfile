# Stage 1: Build stage for dependencies
FROM python:3.11-slim as builder

WORKDIR /app

# Install build essentials for any packages that need compilation
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Final image
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages from the builder stage
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Copy application code
COPY scout_agent.py .

# The agent is triggered by environment variables when run as a Fargate task
# The CMD is a fallback for local testing or direct invocation
CMD ["python", "scout_agent.py"]
