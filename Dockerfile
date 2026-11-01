FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini gunicorn.conf.py ./
RUN useradd --create-home tracely && mkdir -p /app/data && chown -R tracely:tracely /app
USER tracely
ENV PYTHONUNBUFFERED=1 BIND=0.0.0.0:5000
CMD ["gunicorn", "-c", "gunicorn.conf.py", "src.api.app:app"]
