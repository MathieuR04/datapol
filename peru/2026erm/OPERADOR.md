# Guía del operador — noche ERM 2026

Para correr los resultados de la ONPE **desde una conexión en Perú, sin VPN**. La
ONPE restringe el acceso a Perú y pone un control anti-bot delante del backend:
estos scripts **no** intentan rodear ninguno de los dos. Si la ONPE responde con
el desafío anti-bot, el scraper se detiene solo y lo dice.

## 1. Instalar (una vez, ~5 min)

```bash
# git (si `git --version` falla)
xcode-select --install

# uv, que instala Python y las dependencias
curl -LsSf https://astral.sh/uv/install.sh | sh
# cerrar y abrir la Terminal después de instalar uv
```

## 2. Bajar el código

```bash
git clone https://github.com/MathieuR04/datapol.git
cd datapol/peru/2026erm
uv sync
```

## 3. Prueba corta: 50 mesas, sin publicar

```bash
export DATAPOL_CONTACTO=correo@de.contacto
bash scripts/actualizar_mesas.sh --limite 50 --once --no-push
```

Qué mirar en la salida:

| Salida | Significa | Qué hacer |
|---|---|---|
| `{'resuelta': N, 'pendiente': M}` con números | El acceso funciona | Paso 4 |
| `DETENIDO: … desafío anti-bot` | La ONPE bloquea el acceso automático también desde aquí | Parar. Avisar. No insistir |
| `fallidas=50` sin el mensaje anterior | Otra falla de red o de formato | Mandar la salida completa |

## 4. Mapa de elecciones (una vez)

```bash
uv run python scripts/03_consolida_mesas.py
```

La primera vez sale con código 2 y escribe `docs/id_eleccion_descubrimiento.md`.
**Mandar ese archivo.** Con él se arma `data/reference/id_eleccion.csv`
(`id_eleccion,tipo`, cuatro filas) y se pone en esa ruta.

## 5. La noche

```bash
bash scripts/actualizar_mesas.sh            # bucle; primer barrido ~15 min
```

Cada ciclo: baja actas → consolida → escribe las páginas → `git push` (máximo uno
cada 7 min). Para el push hace falta acceso de colaborador al repo
`MathieuR04/datapol`. **Sin acceso**, correr con `--no-push` y mandar
periódicamente estos dos archivos:

    data/processed/computo_mesa_ERM2026.parquet
    data/processed/resultados_mesa_ERM2026.parquet

Para cortar: `Ctrl+C`. Se puede volver a lanzar cuando sea: retoma donde quedó y
no repite mesas ya resueltas.

## Si algo falla

Mandar la salida completa de la Terminal. No borrar nada de `data/`: el crudo
de `data/raw/` es lo que permite rehacer todo sin volver a pedirle nada a la ONPE.
