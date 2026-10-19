# CICD.md — Flujo de trabajo con GitHub CLI para dos personas y sus agentes

> Repositorio: **`sa2009966/LARIA-IA`** — monorepo del tutor inteligente adaptativo (`backend/` FastAPI · DDD/hexagonal · MongoDB · OpenAI; `frontend/` Astro + React).
> Objetivo: que dos personas y sus agentes de código integren su trabajo **sin un solo conflicto de merge que cueste más de cinco minutos**, y que ningún push rompa el despliegue de Render.
> Se lee completo una vez al inicio. Después se consulta §5 (comandos) y §6 (qué hacer si algo sale mal).

---

## 1. La estrategia en tres reglas

1. **Propiedad por rama = propiedad por área.** Con dos personas, la propiedad mapea directo a las ramas de larga vida del repo: una persona vive en `feature/backend` (edita `backend/`), la otra en `feature/frontend` (edita `frontend/`). Como el nombre de la rama *es* el área, dos personas casi nunca tocan el mismo archivo. Esto elimina el 90% de los conflictos antes de que existan. *(Si por ahora ambas trabajan en `backend/`, la propiedad pasa a ser por subdirectorio/módulo — p. ej. `domain/` vs `infrastructure/` — y se acuerda en el canal quién posee cada uno.)*
2. **El contrato es la API, y cambia con aviso.** El único punto donde el trabajo de las dos personas se encuentra es la frontera HTTP (backend ↔ frontend) y, dentro del backend, los contratos de dominio: eventos + serializadores del outbox, `POLICY_VERSION` de `TutorPolicy`, y los esquemas de agregados. Quien cambia un endpoint o un contrato **avisa en el canal, hace un PR solo con ese cambio, y lo mergea primero**. La otra persona hace `git pull` de `develop` antes de seguir.
3. **Ramas cortas, PRs pequeños, merge por squash, rebase antes de push.** Una rama de tarea vive horas, no días. Un PR es una tarea. `develop` siempre integra verde; `main` solo recibe releases.

### Modelo de ramas (fuente de verdad: README del repo)

```
feature/backend    → develop
feature/frontend   → develop
develop            → main          (release; Render auto-despliega main)
```

- `feature/backend`, `feature/frontend`, `develop` y `main` son **ramas protegidas de larga vida** (las que el `pre-push` del repo ya bloquea contra non-fast-forward).
- El trabajo de cada tarea va en una **rama corta** derivada de la rama de área: `feature/backend-<desc>` o `feature/frontend-<desc>`, y su PR apunta a `develop`.
- **Cuidado con Render:** `main` tiene `autoDeploy: true`. Un push a esa rama despliega. Por eso el gate de pytest es obligatorio antes de tocarla.

---

## 2. Instalación de GitHub CLI (una vez por persona)

### macOS
```bash
brew install gh
```

### Ubuntu / Debian
```bash
(type -p wget >/dev/null || sudo apt install wget -y) \
&& sudo mkdir -p -m 755 /etc/apt/keyrings \
&& wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg \
   | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
&& sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
&& echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
   | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
&& sudo apt update && sudo apt install gh -y
```

### Windows
```powershell
winget install --id GitHub.cli
```

### Verificar
```bash
gh --version        # 2.x
git --version       # 2.4x
```

### Autenticación
```bash
gh auth login
# → GitHub.com → HTTPS → Y (autenticar git con credenciales de gh) → Login with a web browser
gh auth status      # debe decir "Logged in to github.com"
gh auth setup-git   # git usa gh como credential helper: no más contraseñas
```

### Identidad de git (una vez)
```bash
git config --global user.name  "Nombre Apellido"
git config --global user.email "correo@ejemplo.com"
git config --global pull.rebase true          # pull siempre hace rebase, nunca merge commit
git config --global rebase.autoStash true     # stash automático al rebasear con cambios locales
git config --global push.autoSetupRemote true # primer push crea la rama remota sin -u
git config --global init.defaultBranch main
```

Las tres últimas líneas son las que evitan el 80% de los enredos con agentes.

---

## 3. Puesta a punto del clon (una vez por persona, ya con el repo clonado)

Ambas personas **ya tienen el repo clonado**, así que no hay que descargar nada. Lo que falta es lo que *no* viene activo al clonar y suele olvidarse: **el `pre-push` hook** (git nunca instala hooks automáticamente por seguridad) y la **config de rebase**. Sin el hook, se puede empujar código con pytest en rojo a `main` y romper el deploy de Render.

```bash
cd LARIA-IA        # o donde lo tengas

# 1. asegurar que estás al día con develop y con tu rama de área
git fetch origin
git switch develop && git pull
git switch feature/backend    # o feature/frontend, según tu área

# 2. instalar el hook de pre-push del repo (gate de pytest + anti force-push)
ln -sfn ../../.githooks/pre-push .git/hooks/pre-push
chmod +x .githooks/pre-push .githooks/run-backend-tests.sh

# 3. confirmar la config de rebase (si ya la pusiste en §2 global, esto solo verifica)
git config pull.rebase true
git config rebase.autoStash true
```

Comprobación rápida de que el hook quedó activo:
```bash
test -L .git/hooks/pre-push && echo "hook OK" || echo "FALTA el hook — repetí el paso 2"
```

> El hook es **por clon**, no se versiona en `.git/`. Cada persona lo instala en su propia copia. Si alguien reclona o borra `.git/hooks/`, hay que repetir el paso 2.

### Backend — dependencias y arranque
```bash
cd backend
cp .env.example .env          # rellenar SECRET_KEY y OPENAI_API_KEY; DB_PROVIDER=memory para local
python -m venv .venv && source .venv/bin/activate    # (o el venv que uses)
pip install -r requirements-dev.txt                   # incluye requirements.txt + pytest/cov/mocks
uvicorn src.main:app --reload --port 8000             # API en http://localhost:8000
```

Con Docker (mongo:7 + redis:7 + app), desde `backend/`:
```bash
docker compose up --build -d
# con puertos publicados para inspección local:
docker compose -f docker-compose.yml -f docker-compose.dev-ports.yml up -d
```

### Frontend — dependencias y arranque (cuando `frontend/` esté en develop)
```bash
cd frontend
cp .env.example .env          # PUBLIC_LARIA_API_URL apuntando al backend
pnpm install && pnpm dev
```

### El "check" del proyecto
No hay `Makefile`. La verificación es **pytest con el gate de cobertura que ya define `backend/pytest.ini`** (líneas ≥ 90%, ramas objetivo ≥ 85%). Desde `backend/`:
```bash
python -m pytest tests -q          # corre suite + cobertura; falla si cae bajo el piso
```
Los tests usan `mongomock-motor`, así que **no necesitan Mongo real** ni red. Corren con `DB_PROVIDER=memory`.

---

## 4. Configuración del repo (una vez, por el owner `sa2009966`)

### Proteger `develop` y `main`
Requiere permiso **admin** (el owner). Se protege la rama de integración y la de release; las ramas de área (`feature/backend`, `feature/frontend`) quedan cubiertas por el `pre-push` hook local.

```bash
for BR in develop main; do
  gh api -X PUT repos/sa2009966/LARIA-IA/branches/$BR/protection \
    -H "Accept: application/vnd.github+json" \
    --input - <<'EOF'
{
  "required_status_checks": { "strict": true, "contexts": ["check"] },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_linear_history": true
}
EOF
done
```

`required_pull_request_reviews: null` a propósito: con dos personas, exigir revisión humana en cada PR bloquea más de lo que protege. La protección real es el CI. `required_linear_history: true` obliga a squash o rebase y mantiene el historial legible.

### CI: crear `.github/workflows/check.yml` (hoy el repo no tiene CI)
El status check `check` que exige la protección de arriba **debe existir**. Este workflow lo provee, alineado al stack real (pip + pytest + gate de cobertura de `pytest.ini`):

```yaml
name: check
on:
  pull_request:
    branches: [develop, main]
  push:
    branches: [develop, main, feature/backend]

jobs:
  check:                     # <- este job es el "context" que exige la protección de rama
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    env:
      APP_ENV: development
      DB_PROVIDER: memory
      RATE_LIMIT_BACKEND: memory
      CACHE_BACKEND: memory
      SECRET_KEY: ci-not-a-real-secret
      OPENAI_API_KEY: sk-ci-placeholder
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
          cache: pip
          cache-dependency-path: backend/requirements-dev.txt
      - run: pip install -r requirements-dev.txt
      - run: python -m pytest tests -q     # cobertura y gate vienen de pytest.ini

  # Descomentar cuando frontend/ exista en develop:
  # web:
  #   runs-on: ubuntu-latest
  #   defaults: { run: { working-directory: frontend } }
  #   steps:
  #     - uses: actions/checkout@v4
  #     - uses: pnpm/action-setup@v4
  #       with: { version: 9 }
  #     - uses: actions/setup-node@v4
  #       with: { node-version: 22, cache: pnpm, cache-dependency-path: frontend/pnpm-lock.yaml }
  #     - run: pnpm install --frozen-lockfile
  #     - run: pnpm build
```

> Si activas el job `web`, añade `"web"` al array `contexts` de la protección de rama para que también sea obligatorio.

### Verificar que el CI usa secretos, no el placeholder
Para pruebas que golpeen OpenAI de verdad (no las unitarias), define `OPENAI_API_KEY` como **secret del repo** (`gh secret set OPENAI_API_KEY`) y referéncialo en el workflow. Las pruebas unitarias no lo necesitan: usan stubs.

---

## 5. El flujo de una tarea (lo que hace cada persona y cada agente, cada vez)

```
sincronizar → rama corta → trabajar → pytest verde → commitear → rebasear → push → PR a develop → CI → merge → limpiar
```

### 5.1 Antes de empezar cualquier tarea
```bash
git switch develop
git pull                              # rebase automático por config
git switch -c feature/backend-perfil-cognitivo   # rama corta de área
```
Nombre de rama: `feature/<area>-<dos-o-tres-palabras>`. El área al frente hace que `git branch` se lea como el sprint.

### 5.2 Mientras trabajás
- Commits pequeños y frecuentes. Mensaje: `backend: perfil cognitivo — gate de muestras en AdaptivePolicy`.
- **Nunca** `git add .` sin mirar `git status` antes.
- Si cambias un contrato (endpoint, evento del outbox, `POLICY_VERSION`), es un PR **aparte** y va primero.
- Si necesitás algo que la otra persona acaba de mergear a `develop`:
  ```bash
  git fetch origin
  git rebase origin/develop
  ```

### 5.3 Antes de commitear la versión final
```bash
cd backend && python -m pytest tests -q
```
Si falla (o la cobertura cae bajo el piso), se arregla. No se commitea con pytest en rojo.

### 5.4 Push y PR
```bash
git fetch origin && git rebase origin/develop     # SIEMPRE antes del push final
git push                                          # el pre-push corre pytest otra vez
gh pr create --fill --base develop \
  --title "Perfil cognitivo · gate de muestras + resolución de conflictos de señales" \
  --body  "Cierra los puntos 1 y 4 del plan. Hecho cuando: test abandono+atención⇒short en verde; confidence_expression fuera de AdaptivePolicy."
gh pr checks --watch                              # espera al CI
```

### 5.5 Merge
```bash
gh pr merge --squash --delete-branch --auto
```
`--auto` mergea solo cuando el CI pasa. `--squash` deja un commit por tarea en `develop`. `--delete-branch` limpia la rama corta.

### 5.6 Después del merge
```bash
git switch develop && git pull
```
Y avisá en el canal: **«perfil-cognitivo mergeado a develop»**. La otra persona hace `git pull` antes de su próximo push.

### 5.7 Promover a producción / release
Cuando `develop` está estable y se quiere release:
```bash
git switch main && git pull
gh pr create --base main --head develop --title "release: <versión>" --fill
gh pr merge --merge --auto        # o squash según preferencia de release
```
Recordá que `main` es el sello de release y lo que Render despliega. Un push a `feature/backend` no actualiza el público.

---

## 6. Comandos que los agentes usan (y que se les da como instrucción)

Pegar esto en el prompt del agente (o en `.cursor/hooks`) al inicio de cada sesión:

> Trabajás en `LARIA-IA`, monorepo con `backend/` (FastAPI/DDD/hexagonal/MongoDB/OpenAI). Tu área es **<backend|frontend>** y solo editás esa carpeta. Antes de tocar nada: `git switch develop && git pull && git switch -c feature/<area>-<desc>`. Commits pequeños con prefijo de área. Antes del push final: desde `backend/` corré `python -m pytest tests -q` en verde (respetá el gate de cobertura ≥90%), luego `git fetch origin && git rebase origin/develop`, luego `git push`. Creá el PR con `gh pr create --fill --base develop --title "<título>"`. Esperá el CI con `gh pr checks --watch`. Mergeá con `gh pr merge --squash --delete-branch --auto`. **Nunca** `git push --force` a `feature/backend`, `feature/frontend`, `develop` ni `main` (el pre-push lo bloquea y Render despliega main). Nunca `git add .` sin revisar. Nunca commitees `.env`, claves (`*.pem`, `*.key`, `*service-account*.json`), `*.db`/`*.sqlite3`, `node_modules/`, `frontend/dist/`, ni reportes de `scripts/out/`. Nunca subas la `OPENAI_API_KEY` ni la cadena de Mongo Atlas. Si tocás un endpoint, un evento del outbox o `POLICY_VERSION`, hacelo en un PR aparte y avisá. Si el rebase da conflicto en un archivo que no es de tu área, **detenete y avisá**; no lo resuelvas vos.

### Referencia rápida

| Quiero… | Comando |
|---|---|
| Ver en qué rama estoy y qué cambió | `git status -sb` |
| Ver PRs abiertos del equipo | `gh pr list` |
| Ver el CI de mi PR | `gh pr checks` |
| Ver qué mergearon en develop | `git log --oneline origin/develop -10` |
| Guardar cambios a medias para cambiar de rama | `git stash push -m "tarea a medias"` → `git stash pop` |
| Traer un solo commit de otra rama | `git cherry-pick <sha>` |
| Deshacer el último commit sin perder cambios | `git reset --soft HEAD~1` |
| Ver qué archivos toca un PR | `gh pr diff <n> --name-only` |
| Revisar un PR de la otra persona | `gh pr checkout <n>` → probar → `gh pr review <n> --approve` |
| Correr solo los tests de un módulo | `cd backend && python -m pytest tests/unit/domain -q` |
| Abrir el repo en el navegador | `gh repo view --web` |
| Crear un issue rápido para algo que se rompió | `gh issue create --title "..." --body "..."` |
| Ver el estado del workflow | `gh run list --limit 5` · `gh run view <id> --log-failed` |

---

## 7. Cuando algo sale mal

### Conflicto en rebase
```bash
git rebase origin/develop
# CONFLICT en backend/src/domain/...
```
1. Si el archivo **es de tu área**: abrilo, resolvé, `git add <archivo>`, `git rebase --continue`.
2. Si el archivo **no es de tu área** (o es un contrato de dominio de la otra persona): `git rebase --abort`, avisá en el canal a quien lo posee, y esperá. Resolver a ciegas un agregado o un serializador de eventos de otro es la forma más rápida de romper el motor pedagógico o invalidar el outbox.
3. Si es `pnpm-lock.yaml` o `requirements*.txt`: aceptá la versión de `develop` (`git checkout --theirs <archivo>` durante el rebase) y regenerá con `pnpm install` / `pip install -r requirements-dev.txt`.

### El CI falla y no sé por qué
```bash
gh run view --log-failed
```
Los fallos más comunes aquí:
- **Cobertura bajo el piso** (`--cov-fail-under=90`): añadiste código sin test. Escribí el test o cubrí la rama; no bajes el umbral para "que pase".
- **Un test que dependía de Mongo/Redis real**: los tests deben usar `mongomock-motor` y backends en memoria, no una base local.
- **Contrato HTTP cambiado sin actualizar el otro lado**: si moviste un endpoint, el frontend (o `test_http_contracts.py`) se rompe. Ese cambio debía ir en su propio PR primero.

### Commiteé algo que no debía (`.env`, clave, base de datos)
```bash
git rm --cached backend/.env
git commit -m "chore: quitar .env del índice"
git push
```
Si ya está en `develop`/`main` y es un **secreto** (`OPENAI_API_KEY`, cadena de Mongo Atlas, Redis de Upstash): **rotalo de inmediato** en el proveedor. No hay `git filter-branch` que valga a las tres de la mañana — la clave ya quedó en el historial y hay que invalidarla.

### `develop` (o el deploy de Render) está roto
```bash
git log --oneline -5                          # encontrar el último commit bueno
git revert <sha-del-malo> --no-edit
git push                                       # revert es un commit nuevo: no rompe la protección
```
Nunca `reset --hard` + `push --force` a una rama compartida. El `pre-push` hook y la protección lo bloquean, y si no lo bloquearan, borraría el trabajo de la otra persona y confundiría a Render. Si lo roto está en `main`, el revert además dispara un re-deploy limpio.

### Las dos personas editaron el mismo contrato
Es la única situación que este documento no puede prevenir por completo. Regla: **gana quien posee el contrato** (el backend posee la API y los contratos de dominio). El otro hace `git rebase --abort`, espera el merge del dueño, y reaplica su cambio sobre la versión nueva. Cinco minutos de espera valen más que una hora de contratos mezclados.

---

## 8. Ritmo de integración

| Momento | Qué se hace |
|---|---|
| Al empezar a trabajar | `git switch develop && git pull`. Nunca arrancar una tarea sobre un `develop` viejo |
| Al terminar cada tarea | PR pequeño a `develop`, CI verde, squash-merge, avisar en el canal. Nada vive en una rama de tarea más de un día |
| Antes de un cambio de contrato | Avisar → PR solo del contrato → mergear primero → los demás hacen pull |
| Antes de una demo / entrega | Freeze corto: solo PRs ya abiertos; probar `develop` levantando la API (`uvicorn`) y, si aplica, `docker compose up` |
| Al liberar | `develop → main` vía PR de release; tag `git tag vX.Y && git push --tags` |

---

## 9. Lo que los agentes tienen prohibido

- `git push --force` a `feature/backend`, `feature/frontend`, `develop` o `main` (el `pre-push` ya lo bloquea; no intentar sortearlo).
- `git add .` o `git add -A` sin mostrar `git status` primero.
- Commitear `.env`, `*.pem`, `*.key`, `*.p12`, `*service-account*.json`, `credentials.json`, `*.db`/`*.sqlite3`, `node_modules/`, `frontend/dist/`, `.astro/`, o reportes locales de `scripts/out/` y `*_report.json`.
- Exponer la `OPENAI_API_KEY`, la cadena de MongoDB Atlas o la URL de Redis (Upstash) en código, logs o mensajes de commit.
- Resolver un conflicto en un archivo del área de la otra persona, o en un contrato de dominio (eventos, outbox, `POLICY_VERSION`, agregados) sin que su dueño lo pida.
- Editar un endpoint, un serializador del outbox, `POLICY_VERSION` o `render.yaml` sin que el humano lo pida explícitamente (rompe contratos o el deploy).
- Crear ramas desde otra rama que no sea `develop` (o la rama de área correspondiente).
- Mergear sin CI verde, o bajar `--cov-fail-under` para forzar el verde.

---

## 10. Verificación de que todo está bien (correr al inicio)

```bash
gh auth status                                              # las dos personas: logged in
gh repo view sa2009966/LARIA-IA --json name,visibility      # LARIA-IA
gh api repos/sa2009966/LARIA-IA/branches/develop/protection --jq .required_status_checks.contexts   # ["check"]
git config --get pull.rebase                                # true
test -L .git/hooks/pre-push && echo "hook instalado"        # el pre-push está enlazado
cd backend && python -m pytest tests -q                     # verde, con cobertura sobre el piso
```

Si las líneas responden bien, el flujo está listo y nadie va a perder tiempo en git.
