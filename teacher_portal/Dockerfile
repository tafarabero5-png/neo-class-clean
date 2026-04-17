# Use official Python image
FROM python:3.14-slim-bookworm

WORKDIR /app

# Install system dependencies required by WeasyPrint
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    libglib2.0-0 \
    libxml2 \
    libxslt1.1 \
    libjpeg62-turbo \
    libopenjp2-7 \
    libtiff6 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt
COPY requirements.txt .

# DEBUG: Show the content of requirements.txt
RUN echo "===== requirements.txt content =====" && cat requirements.txt && echo "==================================="

# Install Python packages (and force weasyprint)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir weasyprint==68.1 && \
    python -c "import weasyprint" || (echo "ERROR: weasyprint not installed" && exit 1)

# Copy the rest of the code
COPY . .

# Run the app
CMD gunicorn app:app --bind 0.0.0.0:$PORT