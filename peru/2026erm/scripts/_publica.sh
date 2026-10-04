# _publica.sh — paso común de publicación de los dos actualizar_*.sh.
# Se carga con `source`; usa ERM_DIR, DATAPOL_DIR, PUSH, step y warn del llamador.
#
# Los dos pipelines corren a la vez y publican al mismo repo. El candado
# (un directorio: mkdir es atómico, y macOS no trae flock) evita que se pisen
# en el emisor o en git.

LOCK_DIR="${TMPDIR:-/tmp}/datapol-erm2026-publica.lock"

# GitHub Pages tiene un límite blando de ~10 despliegues por hora. Con ciclos de
# 5 min (y los otros pipelines de datapol publicando al mismo repo) se pasa, y
# los despliegues se encolan o se saltan: el sitio quedaría atrasado justo
# cuando más se mira. El emisor corre en cada ciclo, pero el push sale como
# máximo cada MIN_PUSH_S segundos. Lo que no se empuja queda en disco y viaja
# en el siguiente push: no se pierde nada.
MIN_PUSH_S="${MIN_PUSH_S:-420}"
MARCA_PUSH="${TMPDIR:-/tmp}/datapol-erm2026-ultimo-push"

# El candado se suelta explícitamente y no con `trap … RETURN`: ese trap queda
# armado después de que la función vuelve y puede borrar el candado del otro
# proceso en cualquier retorno posterior.
publica() {
  # Candado huérfano (proceso muerto con el candado tomado): a los 10 min se suelta.
  if [[ -d "$LOCK_DIR" ]] && [[ -n "$(find "$LOCK_DIR" -maxdepth 0 -mmin +10 2>/dev/null)" ]]; then
    warn "Candado de publicación con más de 10 min — se libera"
    rmdir "$LOCK_DIR" 2>/dev/null
  fi
  for _ in $(seq 1 60); do
    mkdir "$LOCK_DIR" 2>/dev/null && break
    sleep 5
  done
  if [[ ! -d "$LOCK_DIR" ]]; then
    warn "No se obtuvo el candado de publicación — se omite este ciclo"
    return
  fi
  _publica_cuerpo "$1"
  local rc=$?
  rmdir "$LOCK_DIR" 2>/dev/null
  return $rc
}

_publica_cuerpo() {
  local flujo="$1"

  step "Emisor — contrato del sitio"
  if [[ -f "$ERM_DIR/scripts/04_publica_resultados.py" ]]; then
    (cd "$ERM_DIR" && uv run python scripts/04_publica_resultados.py) || {
      warn "publica_resultados falló — el sitio queda en el último ciclo válido"
      return
    }
  else
    warn "04_publica_resultados.py todavía no existe — se omite (solo se archivan datos)"
    return
  fi

  # El emisor escribe directo en peru/2026erm/data, que es lo que sirve el sitio:
  # ya no hay paso de copia. La página es electoral/peru/2026erm/index.html.

  local ahora_s ultimo
  ahora_s=$(date +%s)
  ultimo=$(cat "$MARCA_PUSH" 2>/dev/null || echo 0)
  if (( ahora_s - ultimo < MIN_PUSH_S )); then
    warn "Último push hace $(( ahora_s - ultimo )) s (< ${MIN_PUSH_S} s) — datos al día en disco, push en el próximo ciclo"
    return 0
  fi

  step "Git — staging"
  cd "$DATAPOL_DIR" || return 1
  git add peru/2026erm/data electoral/peru/2026erm 2>/dev/null || true
  local ts
  ts="$(date '+%Y-%m-%d %H:%M')"
  if git diff --cached --quiet -- peru/2026erm/data electoral/peru/2026erm; then
    warn "Sin cambios — nada que commitear."
    return
  fi
  # Solo estas rutas: si el operador tiene otra cosa en staging, no viaja aquí.
  git commit -q -m "data: resultados ERM 2026 ($flujo) — $ts" -- \
    peru/2026erm/data electoral/peru/2026erm
  if $PUSH; then
    step "Git push"
    for attempt in 1 2 3; do
      git push -q && date +%s > "$MARCA_PUSH" && echo -e "\n${GREEN}✔  Publicado — $ts${RESET}" && break
      # Lo típico: otro pipeline de datapol empujó entre medio. Se trae y se
      # reaplica encima; --autostash protege lo que el operador tenga sin commitear.
      warn "Push falló (intento $attempt/3) — trayendo origin y reintentando…"
      git pull --rebase --autostash -q || { git rebase --abort 2>/dev/null; warn "rebase con conflicto — se reintenta en el próximo ciclo"; return 0; }
      sleep 5
    done
  else
    warn "(--no-push: omitiendo push)"
  fi
}
