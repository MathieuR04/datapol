# _publica.sh — paso común de publicación de los dos actualizar_*.sh.
# Se carga con `source`; usa ERM_DIR, DATAPOL_DIR, PUSH, step y warn del llamador.
#
# Los dos pipelines corren a la vez y publican al mismo repo. El candado
# (un directorio: mkdir es atómico, y macOS no trae flock) evita que se pisen
# en el emisor o en git.

LOCK_DIR="${TMPDIR:-/tmp}/datapol-erm2026-publica.lock"

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
  if [[ -f "$ERM_DIR/scripts/05_publica_resultados.py" ]]; then
    (cd "$ERM_DIR" && uv run python scripts/05_publica_resultados.py) || {
      warn "publica_resultados falló — el sitio queda en el último ciclo válido"
      return
    }
  else
    warn "05_publica_resultados.py todavía no existe — se omite (solo se archivan datos)"
    return
  fi

  # El emisor escribe directo en peru/2026erm/data, que es lo que sirve el sitio:
  # ya no hay paso de copia. La página es electoral/peru/2026erm/index.html.

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
      git push -q && echo -e "\n${GREEN}✔  Publicado — $ts${RESET}" && break
      warn "Push falló (intento $attempt/3) — reintentando en 10s…"
      sleep 10
    done
  else
    warn "(--no-push: omitiendo push)"
  fi
}
