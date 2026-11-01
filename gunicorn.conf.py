import os

bind = os.getenv("BIND", "127.0.0.1:5000")
workers = int(os.getenv("WEB_CONCURRENCY", "2"))
worker_class = "uvicorn.workers.UvicornWorker"  # FastAPI requires ASGI worker
threads = 1
timeout = 60
accesslog = "-"
errorlog = "-"
# Requests never start model training in API workers.
