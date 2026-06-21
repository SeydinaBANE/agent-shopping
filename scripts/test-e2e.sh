#!/usr/bin/env bash
set -euo pipefail

APP_NAME="agent-shopping"
ARTILLERY_IMAGE="artilleryio/artillery:latest"
COMPOSE_FILE="docker-compose.yml"
SMOKE_FILE="artillery/smoke.yml"
BENCHMARK_FILE="artillery/benchmark.yml"
REPORT_DIR="artillery/reports"
LAMBDA_URL="http://localhost:9000"

usage() {
    echo "Usage: $0 [smoke|benchmark]"
    echo "  smoke     — Run smoke tests (default)"
    echo "  benchmark — Run benchmark (load) tests"
    exit 1
}

MODE="${1:-smoke}"
if [ "$MODE" != "smoke" ] && [ "$MODE" != "benchmark" ]; then
    usage
fi

cleanup() {
    echo "→ Arrêt des services..."
    docker compose -f "$COMPOSE_FILE" down --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

echo "→ Démarrage de l'infrastructure locale..."
docker compose -f "$COMPOSE_FILE" up -d --wait

echo "→ Attente que le Lambda RIE soit prêt..."
for i in $(seq 1 30); do
    if curl -sf "$LAMBDA_URL/2015-03-31/functions/function/invocations" -d '{}' > /dev/null 2>&1; then
        echo "  ✓ Lambda prêt (tentative $i)"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "  ✗ Lambda non disponible après 30 tentatives"
        exit 1
    fi
    sleep 1
done

echo "→ Seed OpenSearch (RAG)..."
if python3 scripts/seed-opensearch.py 2>/dev/null; then
    echo "  ✓ OpenSearch seedé"
else
    echo "  ⚠ Seed ignoré (MOCK_API=true, pas nécessaire)"
fi

mkdir -p "$REPORT_DIR"
REPORT_FILE="$REPORT_DIR/report-$(date +%Y%m%d-%H%M%S).json"

if [ "$MODE" = "benchmark" ]; then
    echo "→ Lancement du benchmark Artillery..."
    echo "  Fichier: $BENCHMARK_FILE"
    echo "  Rapport: $REPORT_FILE"

    docker run --rm --network host \
        -v "$(pwd)/artillery:/artillery" \
        "$ARTILLERY_IMAGE" \
        run "/artillery/benchmark.yml" \
        --output "/artillery/reports/$(basename "$REPORT_FILE")" \
        --record

    echo "→ Résumé du benchmark:"
    if command -v jq &>/dev/null; then
        jq '.aggregate' "$REPORT_FILE"
    fi
else
    echo "→ Lancement du smoke test Artillery..."
    echo "  Fichier: $SMOKE_FILE"
    echo "  Rapport: $REPORT_FILE"

    docker run --rm --network host \
        -v "$(pwd)/artillery:/artillery" \
        "$ARTILLERY_IMAGE" \
        run "/artillery/smoke.yml" \
        --output "/artillery/reports/$(basename "$REPORT_FILE")"

    echo "→ Résultat du smoke test:"
    python3 -c "
import json, sys
with open('$REPORT_FILE') as f:
    report = json.load(f)
agg = report.get('aggregate', {})
scenarios = agg.get('scenarios', {})
print(f'  Scénarios: {scenarios.get(\"total\")} total, {scenarios.get(\"passed\")} passé(s), {scenarios.get(\"failed\")} échoué(s)')
codes = agg.get('codes', {})
for code, count in sorted(codes.items()):
    print(f'  HTTP {code}: {count}')
"
fi

echo "→ E2E terminé."
