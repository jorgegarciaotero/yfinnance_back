# Use a lightweight Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (optional but recommended for stability)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the source code
COPY src/ ./src/

# Set Python path so it can find your modules
ENV PYTHONPATH=/app

# This doesn't need an ENTRYPOINT here, we will define it in the Job