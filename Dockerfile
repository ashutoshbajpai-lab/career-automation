FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV HEADLESS=false
ENV DISPLAY=:99
ENV PORT=5055
ENV HOST=0.0.0.0

# Install Xvfb virtual framebuffer and X11 utilities to support headed browser evasion
RUN apt-get update && apt-get install -y xvfb xauth && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Ensure Playwright browser is ready
RUN playwright install chromium

# Copy codebase
COPY . .

RUN chmod +x start.sh

# Expose default port
EXPOSE 5055

CMD ["./start.sh"]

