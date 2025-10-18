FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Scout agent code
COPY scout_agent.py .

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run Scout agent
CMD ["python", "scout_agent.py"]