# 1. Start with a minimal Python base image
FROM python:3.11-slim

# 2. Add a non-root user for security
# This prevents code in the container from running as root
RUN useradd -m scraperuser
USER scraperuser
WORKDIR /home/scraperuser

# 3. Install only the necessary libraries
# This is the "allow-list" of libraries the LLM can use
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy the execution script into the container
COPY executor.py .

# 5. Define the entrypoint
# This is the command that runs when the container starts
ENTRYPOINT ["python", "executor.py"]