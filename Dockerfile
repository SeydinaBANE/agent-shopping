# Stage 1: Builder
FROM public.ecr.aws/lambda/python:3.13 AS builder

WORKDIR /build
COPY lambda/requirements.txt ./
RUN pip install -r requirements.txt -t /build/vendor

# Stage 2: Runtime
FROM public.ecr.aws/lambda/python:3.13 AS runtime

ARG VERSION=0.1.0
LABEL org.opencontainers.image.version=${VERSION}
LABEL org.opencontainers.image.source=https://github.com/ekkiden/agent-shopping
LABEL org.opencontainers.image.description="Agent Shopping — Lambda runtime"

COPY --from=builder /build/vendor /var/lang/lib/python3.12/site-packages

COPY lambda/handler.py   /var/task/handler.py
COPY lambda/adapter.py   /var/task/adapter.py

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD curl -f http://localhost:8080/2015-03-31/functions/function/invocations -d '{}' || exit 1

CMD ["handler.lambda_handler"]
