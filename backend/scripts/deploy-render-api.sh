#!/usr/bin/env bash
# Despliega / actualiza el Web Service LARIA en Render vía API.
# NO imprime secretos.
#   export RENDER_API_KEY='rnd_...'   # https://dashboard.render.com/u/settings#api-keys
# Lee OPENAI_API_KEY desde backend/.env (gitignored).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="$ROOT/backend/.env"
API="https://api.render.com/v1"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [[ -z "${RENDER_API_KEY:-}" ]]; then
  echo "Falta RENDER_API_KEY." >&2
  echo "Créala en: https://dashboard.render.com/u/settings#api-keys" >&2
  echo "Luego: export RENDER_API_KEY='rnd_...' && $0" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "No existe $ENV_FILE" >&2
  exit 1
fi

OPENAI_API_KEY="$(python3 -c "
from pathlib import Path
for line in Path(r'$ENV_FILE').read_text().splitlines():
    if line.startswith('OPENAI_API_KEY='):
        print(line.split('=',1)[1].strip().strip(chr(34)).strip(chr(39)), end='')
        break
")"

if [[ -z "$OPENAI_API_KEY" ]]; then
  echo "OPENAI_API_KEY vacío en backend/.env" >&2
  exit 1
fi

SECRET_KEY="$(openssl rand -hex 32)"
CORS_ORIGINS='["http://localhost:4321","https://localhost:4321"]'

auth=(-H "Authorization: Bearer ${RENDER_API_KEY}" -H "Accept: application/json" -H "Content-Type: application/json")

echo "==> Obteniendo owner Render..."
curl -sS "${auth[@]}" "$API/owners" >"$TMP/owners.json"
OWNER_ID="$(python3 -c "
import json
from pathlib import Path
data=json.loads(Path('$TMP/owners.json').read_text())
items=data if isinstance(data,list) else data.get('data',[])
if not items:
    raise SystemExit('')
first=items[0]
owner=first.get('owner', first)
print(owner.get('id') or '', end='')
")"

if [[ -z "$OWNER_ID" ]]; then
  echo "No se pudo obtener owner (¿API key inválida o sin permisos?)." >&2
  exit 1
fi
echo "    owner ok"

python3 -c "
import json, os
from pathlib import Path
vars_list = [
  {'key':'APP_ENV','value':'development'},
  {'key':'DB_PROVIDER','value':'memory'},
  {'key':'RATE_LIMIT_BACKEND','value':'memory'},
  {'key':'EVENT_BUS_BACKEND','value':'memory'},
  {'key':'CACHE_BACKEND','value':'memory'},
  {'key':'IA_PROVIDER','value':'openai'},
  {'key':'OPENAI_MODEL','value':'gpt-4o-mini'},
  {'key':'OPENAI_MODEL_DEFAULT','value':'gpt-4o-mini'},
  {'key':'DEBUG','value':'false'},
  {'key':'ENABLE_DOCS','value':'true'},
  {'key':'RATE_LIMIT_ENABLED','value':'true'},
  {'key':'LOG_LEVEL','value':'INFO'},
  {'key':'LOG_FORMAT','value':'text'},
  {'key':'METRICS_ENABLED','value':'true'},
  {'key':'ACCESS_TOKEN_EXPIRE_MINUTES','value':'60'},
  {'key':'SECRET_KEY','value':os.environ['SECRET_KEY']},
  {'key':'OPENAI_API_KEY','value':os.environ['OPENAI_API_KEY']},
  {'key':'CORS_ORIGINS','value':os.environ['CORS_ORIGINS']},
]
Path('$TMP/env.json').write_text(json.dumps(vars_list))
" 

export SECRET_KEY OPENAI_API_KEY CORS_ORIGINS

echo "==> Buscando servicio laria-backend..."
curl -sS "${auth[@]}" "$API/services?limit=50" >"$TMP/services.json"
SERVICE_ID="$(python3 -c "
import json
from pathlib import Path
data=json.loads(Path('$TMP/services.json').read_text())
items=data if isinstance(data,list) else data.get('data',[])
for row in items:
    svc=row.get('service', row)
    if svc.get('name')=='laria-backend':
        print(svc.get('id',''), end='')
        break
")"

if [[ -n "$SERVICE_ID" ]]; then
  echo "==> Actualizando env vars y disparando deploy ($SERVICE_ID)..."
  curl -sS -X PUT "${auth[@]}" "$API/services/$SERVICE_ID/env-vars" \
    --data @"$TMP/env.json" >"$TMP/env-put.json"
  curl -sS -X POST "${auth[@]}" "$API/services/$SERVICE_ID/deploys" \
    -d '{"clearCache":"do_not_clear"}' >"$TMP/deploy.json"
  python3 -c "
import json
from pathlib import Path
d=json.loads(Path('$TMP/deploy.json').read_text())
deploy=d.get('deploy', d)
print('    deploy:', deploy.get('id') or deploy.get('status') or 'triggered')
"
else
  echo "==> Creando Web Service Docker (free)..."
  python3 -c "
import json
from pathlib import Path
env=json.loads(Path('$TMP/env.json').read_text())
body={
  'type': 'web_service',
  'name': 'laria-backend',
  'ownerId': '$OWNER_ID',
  'repo': 'https://github.com/sa2009966/LARIA-IA',
  'branch': 'main',
  'autoDeploy': 'yes',
  'rootDir': 'backend',
  'runtime': 'docker',
  'dockerfilePath': './Dockerfile',
  'dockerCommand': \"sh -c 'uvicorn src.main:app --host 0.0.0.0 --port \$PORT'\",
  'plan': 'free',
  'region': 'oregon',
  'healthCheckPath': '/health',
  'envVars': env,
}
Path('$TMP/create.json').write_text(json.dumps(body))
"
  curl -sS -X POST "${auth[@]}" "$API/services" --data @"$TMP/create.json" >"$TMP/create-out.json"
  SERVICE_ID="$(python3 -c "
import json,sys
from pathlib import Path
d=json.loads(Path('$TMP/create-out.json').read_text())
svc=d.get('service', d)
sid=svc.get('id','')
if not sid:
    msg=d.get('message') or d.get('error') or str(list(d.keys()))
    print(msg[:300], file=sys.stderr)
print(sid, end='')
")"
  if [[ -z "$SERVICE_ID" ]]; then
    echo "Falló la creación del servicio." >&2
    exit 1
  fi
  echo "    creado: $SERVICE_ID"
fi

echo "==> Consultando URL..."
sleep 2
curl -sS "${auth[@]}" "$API/services/$SERVICE_ID" >"$TMP/svc.json"
python3 -c "
import json
from pathlib import Path
d=json.loads(Path('$TMP/svc.json').read_text())
svc=d.get('service', d)
details=svc.get('serviceDetails') or {}
url=details.get('url') or svc.get('url') or ''
print('SERVICE_ID=$SERVICE_ID')
print('URL=' + (url or '(pendiente en dashboard)'))
if url:
    print('Health=' + url.rstrip('/') + '/health')
    print('Docs=' + url.rstrip('/') + '/docs')
    print('API=' + url.rstrip('/') + '/api/v1')
"
echo "Secretos no impresos. Listo."
