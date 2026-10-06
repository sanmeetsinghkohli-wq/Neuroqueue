# NeuroQueue API. Build from the repository root:
#   docker build -t neuroqueue-api .     (this root copy is what Railway builds)
FROM python:3.11-slim
WORKDIR /srv
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
# model, thresholds, metrics and the demo set (model.pt is not needed for serving)
COPY ml/artifacts ml/artifacts
RUN rm -f ml/artifacts/model.pt ml/artifacts/splits.json
WORKDIR /srv/backend
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
