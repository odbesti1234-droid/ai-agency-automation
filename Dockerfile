FROM python:3.11-slim

WORKDIR /app

# System deps for Playwright + CJK fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# CPU-only torch first — prevents sentence-transformers from pulling CUDA torch (~3GB)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Rest of Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright browser (no --with-deps since system deps already installed above)
RUN python -m playwright install chromium

# App code
COPY . .

CMD ["python", "-m", "src.scheduler.cron"]
