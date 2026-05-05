# Use Python 3.11
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Set environment variables for Python
ENV PYTHONIOENCODING=utf-8
ENV PYTHONUTF8=1

# Run the bot
CMD ["python", "main_cloud.py"]