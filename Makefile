.PHONY: help install lint typecheck test build clean docker-build docker-push pre-commit-init format deploy-widget

APP_NAME      ?= agent-shopping
AWS_ACCOUNT   ?= $(shell aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "unknown")
AWS_REGION    ?= $(shell aws configure get region 2>/dev/null || echo "eu-west-1")
WIDGET_BUCKET ?= $(APP_NAME)-widget-$(AWS_ACCOUNT)-$(AWS_REGION)
VERSION       ?= $(shell cat VERSION 2>/dev/null || echo "0.1.0")
REGISTRY      ?= ghcr.io
OWNER         ?= ekkiden
IMAGE_NAME    ?= $(REGISTRY)/$(OWNER)/$(APP_NAME)

help:
	@echo "Usage:"
	@echo "  make install         Install all dependencies"
	@echo "  make lint            Run linters (ruff)"
	@echo "  make typecheck       Run type checker (mypy)"
	@echo "  make test            Run tests"
	@echo "  make build           Package Lambda + Widget"
	@echo "  make e2e             Run smoke E2E tests (local)"
	@echo "  make e2e-benchmark   Run benchmark E2E tests (local)"
	@echo "  make deploy-widget   Upload widget to S3 + invalidate CloudFront"
	@echo "  make clean           Remove build artifacts"
	@echo "  make docker-build    Build Docker image"
	@echo "  make docker-push     Push Docker image to ghcr.io"
	@echo "  make pre-commit-init Install pre-commit hooks"
	@echo "  make format          Format code (ruff)"

install:
	pip install -r lambda/requirements-dev.txt
	pre-commit install

lint:
	ruff check lambda/ scripts/ tests/
	ruff format --check lambda/ scripts/ tests/

typecheck:
	mypy lambda/ scripts/ tests/

test:
	pytest tests/ -v --cov=lambda/ --cov-report=term-missing

build: test lint typecheck
	cd widget && npm ci && npm run build
	cd lambda && pip install -r requirements.txt -t build/ 2>/dev/null || mkdir -p build
	cp lambda/handler.py lambda/build/
	cp lambda/adapter.py lambda/build/
	cp lambda/auth.py lambda/build/

clean:
	rm -rf lambda/build/
	rm -rf widget/dist/
	rm -rf .pytest_cache/
	rm -rf *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

docker-build:
	docker build \
		--build-arg VERSION=$(VERSION) \
		-t $(IMAGE_NAME):$(VERSION) \
		-t $(IMAGE_NAME):latest \
		.

docker-push: docker-build
	docker push $(IMAGE_NAME):$(VERSION)
	docker push $(IMAGE_NAME):latest

deploy-widget: build
	@echo "Uploading widget to s3://$(WIDGET_BUCKET)/..."
	aws s3 cp widget/dist/agent-shopping.min.js s3://$(WIDGET_BUCKET)/agent-shopping.min.js --cache-control "public, max-age=31536000, immutable"
	aws s3 cp widget/dist/agent-shopping.min.js.map s3://$(WIDGET_BUCKET)/agent-shopping.min.js.map --cache-control "public, max-age=31536000, immutable"
	@echo "Uploaded widget version $(VERSION)"

pre-commit-init:
	pre-commit install
	pre-commit install --hook-type pre-push

format:
	ruff format lambda/ scripts/ tests/

e2e:
	scripts/test-e2e.sh smoke

e2e-benchmark:
	scripts/test-e2e.sh benchmark
