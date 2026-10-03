FROM python:3.12-slim
WORKDIR /app
COPY services/bank-sync/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# `shared/` (backup rotation, used by all three backup-writing services)
# lives at the repo root, so the build context is the repo root too -- see
# docker-compose.yml's `build.context` for this service.
COPY shared ./shared
COPY services/bank-sync/app ./app
ENV DATA_DIR=/data
VOLUME ["/data"]
EXPOSE 8003
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
