# Sistema Difuso de Gestión del Consumo Eléctrico Doméstico

Backend de un sistema de inferencia difusa **tipo Mamdani** que recomienda un **nivel de ahorro
energético (0–100 %)** para una vivienda a partir de tres entradas: la potencia demandada, la
cantidad de personas presentes y la hora del día.

Se ofrece como **API REST** (FastAPI) y como **CLI**. Ambas comparten la misma capa de servicio, por
lo que producen exactamente los mismos resultados.

---

## Contenido

1. [Inicio rápido](#1-inicio-rápido)
2. [Instalación](#2-instalación)
3. [Configuración](#3-configuración)
4. [Uso de la API](#4-uso-de-la-api)
5. [Uso de la CLI](#5-uso-de-la-cli)
6. [El modelo difuso](#6-el-modelo-difuso)
7. [Arquitectura](#7-arquitectura)
8. [Pruebas y calidad](#8-pruebas-y-calidad)
9. [Despliegue con Docker](#9-despliegue-con-docker)
10. [Versiones y compatibilidad](#10-versiones-y-compatibilidad)

---

## 1. Inicio rápido

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# API
uvicorn main:app --reload                       # http://localhost:8000/docs

# CLI
python cli.py --consumo 1900 --personas 3 --hora 12
```

Resultado esperado para 1900 W, 3 personas, 12:00 → **46,72 % · Ahorro moderado**.

## 2. Instalación

**Requisitos:** Python 3.11.

El proyecto usa `pip` con archivos `requirements*.txt` (no Poetry). `pyproject.toml` contiene los
metadatos y la configuración de `pytest`, `ruff` y `black`.

| Archivo | Contenido |
| --- | --- |
| `requirements.txt` | Dependencias de ejecución, con versión exacta. |
| `requirements-dev.txt` | Lo anterior + `pytest`, `httpx`, `ruff`, `black`. |

```bash
pip install -r requirements.txt        # solo ejecutar
pip install -r requirements-dev.txt    # ejecutar y desarrollar
```

## 3. Configuración

Se lee de variables de entorno o de un archivo `.env` (copie `.env.example`).

| Variable | Defecto | Descripción |
| --- | --- | --- |
| `CORS_ALLOWED_ORIGINS` | `["http://localhost:3000"]` | Orígenes CORS: lista JSON o valores separados por comas. Nunca se usa `*`. |
| `LOG_LEVEL` | `INFO` | Con `DEBUG` se registran además las reglas activadas de cada evaluación. |
| `LOG_JSON` | `false` | `true` emite cada log como una línea JSON. |
| `ENVIRONMENT` | `dev` | `dev` o `prod`. |
| `PASO_SALIDA` | `0.01` | Resolución del universo de salida para el centroide (`0 < paso ≤ 1`). |
| `MAX_LOTE` | `1000` | Máximo de ítems en `/api/evaluar/lote`. |
| `MAX_PASOS_BARRIDO` | `500` | Máximo de puntos en `/api/barrido`. |
| `BACKEND_PORT` | `8000` | Puerto publicado por `docker-compose`. |

> **Rendimiento:** con `PASO_SALIDA=0.01` una evaluación tarda ≈ 9 ms y un lote de 1000 ítems ≈ 9 s.
> Con `0.1` es unas 10 veces más rápido y el resultado cambia menos de 0,001 puntos.

## 4. Uso de la API

```bash
uvicorn main:app --reload                                    # desarrollo
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2      # producción
```

Documentación interactiva (Swagger): <http://localhost:8000/docs>.

### Endpoints

| Método | Ruta | Descripción |
| --- | --- | --- |
| `POST` | `/api/evaluar` | Una evaluación. |
| `POST` | `/api/evaluar/lote` | Varias evaluaciones; la validación es atómica. |
| `POST` | `/api/barrido` | Varía una variable y mantiene fijas las otras dos. |
| `GET` | `/api/reglas` | Las 36 reglas de la base. |
| `GET` | `/api/membresias` | Curvas de pertenencia muestreadas de las cuatro variables. |
| `GET` | `/api/grafico/agregacion?consumo_w=&personas=&hora=` | PNG con la agregación y el centroide de esa entrada. |
| `GET` | `/api/grafico/membresias/{n}` | PNG de las funciones de pertenencia (`n` = 1, 2 o 3; otro valor → 404). |
| `GET` | `/health` | `200` si reglas, funciones de salida y una evaluación de prueba están correctas; si no, `503`. |

### Entradas válidas

| Campo | Rango | Notas |
| --- | --- | --- |
| `consumo_w` | 0 – 3000 | Potencia demandada en W. |
| `personas` | 0 – 6 | Admite fraccionarios (promedios). |
| `hora` | 0 – 24 | Hora decimal (`14.5` = 14:30). Las 0 h y las 24 h son equivalentes. |
| `id_evaluacion` | ≤ 100 caracteres | Opcional; se devuelve tal cual (útil en lotes). |

Los valores fuera de rango, `NaN` o `inf` se rechazan con **422**: nunca se recortan en silencio.

### Ejemplo

```bash
curl -s -X POST http://localhost:8000/api/evaluar \
  -H "Content-Type: application/json" \
  -d '{"id_evaluacion": "demo", "consumo_w": 1900, "personas": 3, "hora": 12}'
```

```json
{
  "id_evaluacion": "demo",
  "entradas": {"consumo_w": 1900.0, "personas": 3.0, "hora": 12.0},
  "salida_pct": 46.72,
  "interpretacion": "Ahorro moderado",
  "accion_sugerida": "Apagar equipos no esenciales",
  "fuzzificacion": {
    "consumo": {"bajo": 0.0, "medio": 0.4286, "alto": 0.1429},
    "personas": {"pocas": 0.0, "moderadas": 1.0, "muchas": 0.0},
    "hora": {"madrugada": 0.0, "manana": 0.25, "tarde": 0.25, "noche": 0.0}
  },
  "reglas_activadas": [
    {"regla": "R18", "consumo": "Medio", "personas": "Moderadas", "hora": "Mañana",
     "salida": "Bajo", "alpha": 0.25, "calculo": "mín(0,4286; 1,0000; 0,2500)"}
  ]
}
```

*(La lista de reglas está abreviada; este caso activa R18, R19, R30 y R31.)*

### Errores

Todas las respuestas de error comparten el formato `{"detail": "...", "error_code": "..."}`.

| Código HTTP | `error_code` | Cuándo |
| --- | --- | --- |
| 422 | `VALIDATION_ERROR` | Entrada inválida. Incluye `errors` con el campo exacto (p. ej. `evaluaciones[2].hora`). |
| 404 | `FIGURA_NO_ENCONTRADA` | `n` fuera de {1, 2, 3} en `/api/grafico/membresias/{n}`. |
| 500 | `MOTOR_DIFUSO_ERROR`, `DEFUZZIFICACION_ERROR`, … | Fallo interno del motor. |

## 5. Uso de la CLI

### Modos

```bash
# Directo: una evaluación
python cli.py --consumo 1900 --personas 3 --hora 12
python cli.py --consumo 1900 --personas 3 --hora 14:30      # la hora admite 14.5 o HH:MM

# Interactivo: sin argumentos; pide los valores en bucle hasta escribir 'q'
python cli.py

# Lote: CSV con columnas id,consumo_w,personas,hora
python cli.py --csv entradas.csv --salida resultados.csv
```

### Opciones

| Opción | Efecto |
| --- | --- |
| `--detalle` | Muestra el paso a paso: fuzzificación, reglas activadas con su α y cálculo, y centroide. |
| `--grafico RUTA.png` | Guarda la figura de agregación de la entrada (en lote, una por fila con el id como sufijo). |
| `--figuras-informe DIR` | Genera `figura_1.png … figura_4.png` (no requiere entradas). |
| `--formato {tabla,json,csv}` | Formato de salida. Por defecto `tabla`; con `--salida`, `csv`. |
| `--barrido {consumo,personas,hora}` | Varía una variable con `--desde X --hasta Y --pasos N`; fije las otras con `--consumo/--personas/--hora`. |
| `-v`, `--verbose` | Log detallado en stderr. |

```bash
python cli.py --barrido hora --desde 0 --hasta 24 --pasos 25 --consumo 1900 --personas 3
```

### Códigos de salida

| Código | Significado |
| --- | --- |
| `0` | Éxito. |
| `2` | Error de uso o de validación de las entradas. |
| `1` | Error del motor o inesperado. |

Los errores se muestran como mensajes legibles; nunca un traceback crudo.

### Casos de ejemplo

`data/casos_informe.csv` contiene cuatro evaluaciones contrastantes. Son solo datos de demostración:
el sistema acepta cualquier combinación dentro de los rangos.

```bash
python cli.py --csv data/casos_informe.csv --detalle
```

| id | Consumo (W) | Personas | Hora | Salida (%) | Interpretación |
| --- | --- | --- | --- | --- | --- |
| caso-1 | 300 | 5 | 15:00 | 9,29 | Sin necesidad de ahorro |
| caso-2 | 1000 | 4 | 08:00 | 22,54 | Ahorro leve |
| caso-3 | 1900 | 3 | 12:00 | 46,72 | Ahorro moderado |
| caso-4 | 2800 | 1 | 02:00 | 90,71 | Ahorro crítico |

## 6. El modelo difuso

### Variables

| Variable | Universo | Conjuntos (tipo · parámetros) |
| --- | --- | --- |
| **Consumo** (W) | 0 – 3000 | Bajo (trap. 0, 0, 500, 1200) · Medio (tri. 700, 1500, 2200) · Alto (trap. 1800, 2500, 3000, 3000) |
| **Personas** | 0 – 6 | Pocas (trap. 0, 0, 1, 2) · Moderadas (tri. 1, 3, 5) · Muchas (trap. 4, 5, 6, 6) |
| **Hora** (h, circular) | 0 – 24 | Madrugada (máx de trap. 0, 0, 4, 7 y trap. 22, 24, 24, 24) · Mañana (tri. 5, 9, 13) · Tarde (tri. 11, 15, 19) · Noche (máx de trap. 17, 21, 24, 24 y trap. 0, 0, 0, 2) |
| **Ahorro** (%, salida) | 0 – 100 | Muy bajo (trap. 0, 0, 10, 25) · Bajo (tri. 15, 30, 45) · Medio (tri. 35, 50, 65) · Alto (tri. 55, 70, 85) · Muy alto (trap. 75, 90, 100, 100) |

La hora es **circular**: Madrugada y Noche se componen con `np.fmax` sobre dos trapecios, de modo que
00:00 y 24:00 dan pertenencias idénticas (Madrugada = 1 y Noche = 1) y, por tanto, la misma salida.

### Base de reglas

36 reglas `SI consumo Y personas Y hora ENTONCES ahorro`, una por cada combinación de antecedentes
(`R1`…`R36`, en orden consumo → personas → hora). Salida por franja horaria:

| Consumo | Personas | Madrugada | Mañana | Tarde | Noche |
| --- | --- | --- | --- | --- | --- |
| Bajo | Pocas | Medio | Bajo | Bajo | Medio |
| Bajo | Moderadas | Bajo | Muy bajo | Muy bajo | Bajo |
| Bajo | Muchas | Muy bajo | Muy bajo | Muy bajo | Muy bajo |
| Medio | Pocas | Muy alto | Medio | Alto | Alto |
| Medio | Moderadas | Alto | Bajo | Medio | Medio |
| Medio | Muchas | Medio | Muy bajo | Bajo | Bajo |
| Alto | Pocas | Muy alto | Muy alto | Muy alto | Muy alto |
| Alto | Moderadas | Muy alto | Alto | Alto | Muy alto |
| Alto | Muchas | Alto | Medio | Medio | Alto |

La base se valida al importar el módulo (36 reglas, ids consecutivos, combinaciones completas sin
duplicados, etiquetas válidas); por eso toda entrada activa al menos una regla.

### Inferencia

1. **Fuzzificación** de las tres entradas.
2. **Activación:** `α = mín(μ_consumo, μ_personas, μ_hora)`; solo se conservan las reglas con `α > 0`.
3. **Implicación (MIN) y agregación (MAX):** cada conjunto de salida se recorta al nivel `α` y se
   unen con máximo.
4. **Defuzzificación por centroide** sobre el universo de salida.

### Interpretación de la salida

Intervalos cerrados por la izquierda y abiertos por la derecha, salvo el último.

| Salida (%) | Interpretación | Acción sugerida |
| --- | --- | --- |
| [0, 20) | Sin necesidad de ahorro | Ninguna |
| [20, 40) | Ahorro leve | Recomendaciones de uso eficiente |
| [40, 60) | Ahorro moderado | Apagar equipos no esenciales |
| [60, 80) | Ahorro alto | Reducir cargas de forma activa |
| [80, 100] | Ahorro crítico | Desconectar cargas no prioritarias |

### Precisión y redondeo

El motor trabaja con valores exactos (por ejemplo `α = 1/7`, no `0,14`) y no redondea nada. El
redondeo (2 decimales en la salida, 4 en los grados) se aplica solo al presentar resultados. Así, el
caso 1900/3/12 da 46,72 %, mientras que redondear `α` antes de defuzzificar daría 46,62 %.

> **Sobre la monotonía:** dentro de cada franja horaria, la *etiqueta* de salida de las reglas no baja
> al subir el consumo ni sube al subir las personas. El centroide continuo **no** es monótono (puede
> retroceder hasta ~3 puntos), así que esa propiedad se verifica solo a nivel de reglas.

## 7. Arquitectura

```
proyecto_difuso/
├── fuzzy/                 núcleo difuso
│   ├── membresias.py      universos, funciones de pertenencia y fuzzificación
│   ├── reglas.py          base de 36 reglas + validación + heurística de generación
│   ├── motor.py           pipeline Mamdani (función pura)
│   ├── interpretacion.py  tabla de interpretación de la salida
│   └── graficos.py        figuras PNG (membresías, agregación + centroide)
├── services/
│   └── difuso_service.py  fachada usada por la API y la CLI
├── core/                  configuración, logging y excepciones de dominio
├── schemas/difuso.py      modelos Pydantic v2 de entrada y salida
├── routers/api.py         endpoints /api
├── data/                  casos de ejemplo (CSV)
├── tests/                 pruebas con pytest
├── main.py                aplicación FastAPI
├── cli.py                 interfaz de línea de comandos
├── Dockerfile · docker-compose.yml · .github/workflows/ci.yml
└── pyproject.toml · requirements*.txt · .env.example
```

Flujo: `API / CLI → DifusoService → fuzzy.motor.evaluar → ResultadoInferencia → esquemas`.

### Decisiones de diseño

| Decisión | Motivo |
| --- | --- |
| **Motor puro, sin `Lock`** | `evaluar()` no usa estado mutable compartido (reglas inmutables, funciones de salida de solo lectura, arreglos temporales por llamada), así que varias hebras evalúan en paralelo con resultados idénticos. |
| **scikit-fuzzy a bajo nivel** (`trapmf`, `trimf`, `defuzz`) en lugar de `ControlSystem` | `ControlSystem` guarda estado por simulación (no es seguro entre hilos), oculta el α por regla y los conjuntos recortados, y es más lento. |
| **`Figure` en vez de `pyplot`** | `pyplot` mantiene estado global y no es seguro entre hilos; con `Figure` + `FigureCanvasAgg` cada petición usa objetos locales. |
| **Endpoints `def`, no `async def`** | El cálculo es CPU-bound; FastAPI lo ejecuta en su threadpool sin bloquear el event loop. |
| **Servicio único en `app.state`** | Se instancia una vez en el `lifespan` y se precalculan las funciones de salida. |
| **Logging estándar con formateador JSON opcional** | Cubre el requisito sin añadir `structlog` a las dependencias. |
| **`argparse` en la CLI** | Evita una dependencia extra frente a `typer`. |

## 8. Pruebas y calidad

```bash
pytest               # 174 pruebas
ruff check .
black --check .
```

| Archivo de pruebas | Cubre |
| --- | --- |
| `test_membresias.py` | Valores en puntos clave, hora circular (0 h ≡ 24 h), cobertura del universo, casos degenerados. |
| `test_reglas.py` | 36 reglas, ids, combinaciones, distribución de salidas, heurística, monotonía de etiquetas. |
| `test_interpretacion.py` | Bordes de cada intervalo (0, 19.99, 20, …, 80, 100). |
| `test_motor.py` | 8 casos de referencia, activación exacta de reglas, rango de salida, pureza y concurrencia, `α` exacto vs. redondeado. |
| `test_cli.py` | Modos directo, lote, interactivo y barrido; hora `HH:MM`; errores y códigos de salida; generación de figuras. |
| `test_api.py` | Endpoints, errores 404/422/500, lote atómico, CORS, `/health`. |

La integración continua (`.github/workflows/ci.yml`) ejecuta `ruff`, `black --check` y `pytest` en
cada push y pull request sobre Python 3.11; el build falla si alguno falla.

## 9. Despliegue con Docker

```bash
docker compose up --build
```

- Imagen base `python:3.11-slim`, ejecución con usuario no root y `HEALTHCHECK` contra `/health`.
- El `.env` se inyecta como variables de entorno (es opcional).
- En `docker-compose.yml` hay un servicio `frontend` de ejemplo, comentado.

### Render

El repositorio incluye `render.yaml` para crear un Web Service Docker con chequeo HTTP en
`/health`. Al conectarlo en Render, define `CORS_ALLOWED_ORIGINS` con la URL de producción del
frontend, por ejemplo `['https://tu-proyecto.vercel.app']`. No uses `*`: el backend solo permite
orígenes explícitos. Render inyecta `PORT` y el contenedor lo usa automáticamente.

## 10. Versiones y compatibilidad

Las dependencias están fijadas con `==` (últimas versiones estables en PyPI al 2026-10-07) y la suite
completa pasa con ellas.

| Paquete | Versión | | Paquete | Versión |
| --- | --- | --- | --- | --- |
| fastapi | 0.142.4 | | scikit-fuzzy | **0.5.0** |
| uvicorn[standard] | 0.54.0 | | matplotlib | 3.11.2 |
| pydantic | 2.13.5 | | python-dotenv | 1.2.4 |
| pydantic-settings | 2.15.0 | | pytest | 9.1.1 |
| numpy | 2.4.6 | | httpx | 0.28.1 |
| scipy | 1.17.1 | | ruff · black | 0.16.10 · 26.10.0 |

- scikit-fuzzy 0.5.0 funciona sin cambios con NumPy 2.x y SciPy 1.17: no fue necesario fijar `numpy<2`.
- NumPy 2.5 y SciPy 1.18 requieren Python ≥ 3.12; en Python 3.11 las últimas instalables son las
  indicadas arriba.
- Starlette 1.x avisa de que `TestClient` prefiere `httpx2`. Se mantiene `httpx` y el aviso se
  silencia en `[tool.pytest.ini_options]` de `pyproject.toml`.
