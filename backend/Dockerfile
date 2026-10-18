FROM python:3.13-slim
WORKDIR /app
COPY backend/requirements-deploy.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
ENV PYTHONUNBUFFERED=1
CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"
