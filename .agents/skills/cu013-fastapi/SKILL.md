---
name: cu013-fastapi
description: Operates and maintains the core FastAPI application, endpoints, and server lifecycle.
---

# cu013-fastapi

## Responsibility
Manage FastAPI application configuration, lifespan events, HTTP status codes, routing, and exception handling.

## Allowed Changes
- Adding middleware for request tracing or CORS if required.
- Tuning timeout handling or exception handlers.
- Optimizing lifespan initialization.

## Forbidden Changes
- Adding heavy framework layers (services, repositories, managers) over standard FastAPI routes.
- Adding remote dependency probes inside `GET /health`.
- Creating custom auth schemes when Cloud Run IAM / ADC is mandated.

## Inputs / Contracts
- HTTP requests from client (`GET /health`, `POST /turn`).

## Outputs / Contracts
- Fast JSON HTTP responses conformant with `HealthResponse` and `TurnResponse`.

## Trusted References
- [app/main.py](../../app/main.py)
- [app/contracts.py](../../app/contracts.py)

## Quality Checks
- `pytest tests/test_health.py tests/test_turn.py`
- `ruff check app/main.py`
- `mypy app/main.py`

## STOP Conditions
- Endpoint changes that violate XCALLY IVR expectations.
