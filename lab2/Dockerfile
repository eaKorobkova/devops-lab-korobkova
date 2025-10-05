# Use Python 3.9 slim as base image
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system packages
RUN apt-get update && apt-get install -y \
    curl \
    vim \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application file
COPY app.py .

# Create user with UID 1000
RUN useradd -m -u 1000 appuser

# Switch to appuser
USER appuser

# Expose port 5000
EXPOSE 5000

# Set environment variable
ENV FLASK_ENV=production

# Run the application
CMD ["python", "app.py"]
