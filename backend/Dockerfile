FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements*.txt ./
ARG INSTALL_AGENTS=true
RUN pip install --no-cache-dir -r requirements.txt && if [ "$INSTALL_AGENTS" = "true" ]; then pip install --no-cache-dir -r requirements-agents.txt; fi
RUN useradd -m appuser
COPY backend/app ./app
COPY data ./data
ENV DATA_DIR=/app/data PYTHONUNBUFFERED=1
USER appuser
EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
