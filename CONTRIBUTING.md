# Contribuer

## Branches
- `main` — production, protégée (PR + review obligatoire)
- `develop` — intégration, protégée (PR + CI obligatoire)
- `feat/<description>` — nouvelle fonctionnalité (merge → develop)
- `fix/<description>` — correction (merge → develop)
- `chore/<description>` — CI, config, dépendances (merge → develop)

## Convention de commits
Utiliser [Conventional Commits](https://www.conventionalcommits.org/) :

```
feat: ajouter l'outil rechercher_produits
fix: timeout sur appel API client
chore: mise à jour dependabot
docs: mise à jour ARCHITECTURE.md
refactor: extraire validation JWT
test: ajouter tests adapter
```

## Workflow
1. Créer une branche depuis `develop`
2. Coder + tests
3. `make lint typecheck test` ✅
4. Commit avec conventional commit
5. PR vers `develop` avec le template
6. Review + merge
7. `develop` → `main` déclenche CD

## Pre-commit
```bash
make pre-commit-init
make install
```

## Docker
```bash
make docker-build
make docker-push    # version + latest vers ghcr.io
```
