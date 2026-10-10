# Matiz — Fuzzy Energy-Saving API

![Matiz banner](assets/banner.png)

[![Python](https://img.shields.io/badge/Python-3.11-1B4965?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-1B4965?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![scikit-fuzzy](https://img.shields.io/badge/scikit--fuzzy-0.5.0-1B4965?logo=python&logoColor=white)](https://pythonhosted.org/scikit-fuzzy/)
[![Docker](https://img.shields.io/badge/Docker-1B4965?logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-1B4965.svg)](LICENSE)

Python API and command-line interface for a Mamdani fuzzy inference system that estimates household energy-saving priority from electricity demand, occupancy, and time of day.

It powers the [Matiz frontend](https://github.com/angelariasus/fuzzy-system-frontend), which displays the simulation results, membership degrees, activated rules, output aggregation, and centroid.

## Features

- Mamdani fuzzy inference with 36 rules.
- Input validation for power, occupancy, and time of day.
- Single and batch evaluations.
- Parameter sweeps for simulation and analysis.
- Membership, aggregation, and centroid charts as PNG files.
- REST API with automatic OpenAPI documentation.
- Command-line interface for direct, interactive, and CSV-based execution.
- Docker and Render deployment support.

## Tech stack

- Python 3.11
- FastAPI and Uvicorn
- Pydantic
- NumPy and SciPy
- scikit-fuzzy
- Matplotlib
- Docker

## Requirements

- Python 3.11
- `pip`

## Getting started

1. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   ```

   ```bash
   # macOS / Linux
   source .venv/bin/activate

   # Windows PowerShell
   .venv\Scripts\Activate.ps1
   ```

2. Install the dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Create the environment file:

   ```bash
   cp .env.example .env
   ```

4. Start the development server:

   ```bash
   uvicorn main:app --reload
   ```

The API is available at [http://localhost:8000](http://localhost:8000). Interactive OpenAPI documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs).

## Input domain

| Input | Accepted range |
| --- | --- |
| Electricity demand | 0–3000 W |
| Occupancy | 0–6 people; fractional values are accepted |
| Time of day | 0–24 hours; decimal values are accepted (`14.5` = 14:30) |

The hour is circular: 00:00 and 24:00 represent the same instant. Invalid, non-finite, or out-of-range values are rejected and never silently clamped.

## API overview

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/api/evaluar` | Evaluates one input combination. |
| `POST` | `/api/evaluar/lote` | Evaluates a batch atomically. |
| `POST` | `/api/barrido` | Sweeps one variable while keeping the others fixed. |
| `GET` | `/api/reglas` | Returns the 36-rule fuzzy rule base. |
| `GET` | `/api/membresias` | Returns sampled membership curves. |
| `GET` | `/api/grafico/agregacion` | Returns a PNG of the aggregated output and centroid. |
| `GET` | `/api/grafico/membresias/{n}` | Returns membership-chart PNGs, where `n` is 1, 2, or 3. |
| `GET` | `/health` | Returns the service health status. |

### Evaluation example

```bash
curl -X POST http://localhost:8000/api/evaluar \
  -H "Content-Type: application/json" \
  -d '{"id_evaluacion":"demo","consumo_w":1900,"personas":3,"hora":12}'
```

```json
{
  "id_evaluacion": "demo",
  "entradas": {
    "consumo_w": 1900.0,
    "personas": 3.0,
    "hora": 12.0
  },
  "salida_pct": 46.72,
  "interpretacion": "Ahorro moderado",
  "accion_sugerida": "Apagar equipos no esenciales"
}
```

The complete response also includes membership degrees and the activated rules.

## Command-line interface

Run a direct evaluation:

```bash
python cli.py --consumo 1900 --personas 3 --hora 12
```

Use the interactive mode:

```bash
python cli.py
```

Evaluate a CSV file with `id`, `consumo_w`, `personas`, and `hora` columns:

```bash
python cli.py --csv entradas.csv --salida resultados.csv
```

Generate the report figures:

```bash
python cli.py --figuras-informe figuras
```

Useful options include `--detalle` for the inference steps, `--grafico resultado.png` for an aggregation chart, and `--barrido` for a parameter sweep.

## Configuration

Configuration is read from environment variables or an optional `.env` file.

| Variable | Default | Description |
| --- | --- | --- |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | Allowed frontend origins. |
| `LOG_LEVEL` | `INFO` | Application logging level. |
| `LOG_JSON` | `false` | Emits JSON-formatted logs when enabled. |
| `ENVIRONMENT` | `dev` | Execution environment: `dev` or `prod`. |
| `PASO_SALIDA` | `0.01` | Output-universe resolution for centroid calculation. |
| `MAX_LOTE` | `1000` | Maximum number of evaluations per batch. |
| `MAX_PASOS_BARRIDO` | `500` | Maximum number of points per sweep. |

For local integration with the frontend, add its URL to `CORS_ALLOWED_ORIGINS`. In production, use the deployed frontend URL instead.

## Docker and Render

Build and start the application with Docker Compose:

```bash
docker compose up --build
```

The included `render.yaml` defines a Docker Web Service and checks the `/health` endpoint. Before deploying, configure `CORS_ALLOWED_ORIGINS` with the production frontend URL.

## Project structure

```text
core/          Configuration, logging, and domain exceptions
fuzzy/         Membership functions, rules, inference engine, interpretation, and charts
routers/       FastAPI endpoints
schemas/       Pydantic request and response models
services/      Shared service layer for the API and CLI
tests/         Automated tests
main.py        FastAPI application entry point
cli.py         Command-line interface
```

## Testing and code quality

Install development dependencies:

```bash
pip install -r requirements-dev.txt
```

Run the verification suite:

```bash
pytest
ruff check .
black --check .
```

## License

Distributed under the [MIT License](LICENSE).

## Academic context

Developed for the *Sistemas Inteligentes* course at Universidad Nacional Mayor de San Marcos (UNMSM).
