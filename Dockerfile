# Use official Python image
FROM python:3.14-slim-bookworm

# Set working directory inside container
WORKDIR /app

# Install all system dependencies required by WeasyPrint and common Python packages
RUN apt-get update && apt-get install -y \
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

# Copy requirements and install Python packages
COPY teacher_portal/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Set working directory to where app.py lives
WORKDIR /app/teacher_portal

# Run the app (shell form to allow $PORT expansion)
CMD gunicorn app:app --bind 0.0.0.0:$PORT