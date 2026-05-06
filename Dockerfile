FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create data and logs directories
RUN mkdir -p data logs

# Expose dashboard port
EXPOSE 8080

# Run the supervisor (starts all services)
CMD ["python", "start.py"]
