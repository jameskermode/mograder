FROM python:3.12-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir .
CMD ["mograder", "serve", "demo/course"]
