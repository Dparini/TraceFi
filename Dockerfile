FROM python:3.12-slim
WORKDIR /opt/tracefi
COPY pyproject.toml README.md LICENSE ./
COPY tracefi ./tracefi
RUN pip install --no-cache-dir .
WORKDIR /workspace
ENTRYPOINT ["tracefi"]
CMD ["demo"]
