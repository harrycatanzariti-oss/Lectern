# Build the frontend, then serve it and the API from one small Python image.
FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=web /app/frontend/dist frontend/dist
ENV LECTERN_DATA=/data
WORKDIR /app/backend
CMD ["sh", "-c", "uvicorn lectern.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
