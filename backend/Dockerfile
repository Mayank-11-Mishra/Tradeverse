# Two separate environments allow FYERS and Groww to coexist without a broken aiohttp install.
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app/backend
RUN python -m venv /opt/tradeverse-main \n    && python -m venv /opt/tradeverse-fyers
COPY requirements.txt requirements-fyers-worker.txt ./
RUN /opt/tradeverse-main/bin/python -m pip install --no-cache-dir -r requirements.txt \n    && /opt/tradeverse-fyers/bin/python -m pip install --no-cache-dir -r requirements-fyers-worker.txt \n    && /opt/tradeverse-main/bin/python -m pip check \n    && /opt/tradeverse-fyers/bin/python -m pip check
ENV PATH="/opt/tradeverse-main/bin:${PATH}" \n    FYERS_WORKER_PYTHON=/opt/tradeverse-fyers/bin/python
COPY app ./app
COPY main.py ./main.py
RUN mkdir -p /app/data
EXPOSE 8000
CMD ["sh", "-c", "exec python -m uvicorn app.api.server:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
