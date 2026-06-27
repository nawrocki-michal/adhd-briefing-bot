# ADHD Briefing Bot — self-hostable container
# Build:  docker build -t adhd-briefing .
# Run:    docker run -d --env-file .env -v adhd_data:/data adhd-briefing
FROM python:3.12-slim

# Faster, cleaner Python in containers
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/data/adhd.db

WORKDIR /app

# Install dependencies first (better layer caching) then the package itself.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

# Create an unprivileged user and the data dir BEFORE declaring the volume —
# changes to a VOLUME path made after the VOLUME instruction are discarded.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data \
    && chown -R app:app /app /data

# Persist the SQLite database on a volume so it survives restarts.
VOLUME ["/data"]

USER app

# Long-polling Telegram bot (no inbound port needed).
CMD ["python", "-m", "adhd_briefing.bot"]
