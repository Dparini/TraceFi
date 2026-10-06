FROM python:3.12-slim
WORKDIR /opt/agenttrace
COPY pyproject.toml README.md LICENSE ./
COPY agenttrace ./agenttrace
RUN pip install --no-cache-dir .
WORKDIR /workspace
ENTRYPOINT ["agenttrace"]
CMD ["demo"]
