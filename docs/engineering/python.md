# Estándar de ingeniería Python

Este documento define convenciones de implementación subordinadas a la [SPEC del sistema](../specs/system.md), la [SPEC de acciones de cuenta](../specs/account-actions.md) y los ADR con `Status: Accepted`. No introduce arquitectura ni contratos de producto.

## Python y herramientas

- El runtime objetivo usa Python 3.12.
- [`pyproject.toml`](../../pyproject.toml) es la fuente ejecutable de configuración para Ruff, MyPy y pytest.
- Ruff gobierna lint y formato. No se duplican manualmente sus reglas de estilo.
- Cuando exista código, los gates de Ruff son:

  ```powershell
  python -m ruff check .
  python -m ruff format --check .
  ```

- El runtime nuevo parte con MyPy en modo `strict`. Toda excepción debe ser local, mínima y justificada.
- No se permite `ignore_missing_imports = true` global sin una decisión explícita respaldada por evidencia.

### Packaging transitorio

`packages = []` es una configuración transitoria de la baseline sin runtime. En la misma iteración que cree el primer paquete productivo debe reemplazarse por una configuración explícita de packaging o discovery, verificando `pip install -e ".[dev]"` y que el paquete runtime sea importable desde `.venv`.

No se crean `app/`, paquetes vacíos ni configuración preventiva para anticipar esa iteración.

## I/O asíncrona

- Mantener I/O asíncrona de extremo a extremo cuando la SDK admita `await`.
- No ejecutar I/O bloqueante directamente en el event loop.
- No imponer `async` a funciones puramente síncronas por dogma.
- Reutilizar clientes remotos seguros a nivel de proceso cuando la SDK lo permita.

## Contratos

Usar Pydantic y typing en los boundaries de:

- entrada y salida HTTP;
- salida estructurada del LLM;
- entrada y salida de capacidades externas;
- registros semánticos persistidos.

FastAPI debe validar y filtrar respuestas mediante tipos o `response_model` cuando aplique. Los objetos internos de una SDK o provider no pueden convertirse en contrato público.

## Código

- Crear abstracciones sólo cuando resuelvan un fallo o una conveniencia concreta.
- No crear módulos ceremoniales `utils`, `common` o `helpers` sin cohesión real.
- Los comentarios explican decisiones y razones; no traducen la línea de código.
- No implementar routing semántico productivo por keywords o expresiones regulares.

## Bloques Markdown

- Usar el language fence correcto: `python`, `powershell`, `yaml`, `json`, `dockerfile` u otro lenguaje ejecutable correspondiente.
- Usar `text` para pseudocódigo, diagramas ASCII y output.
- No etiquetar pseudocódigo como código ejecutable.

## Referencias oficiales

- [Ruff configuration](https://docs.astral.sh/ruff/configuration/)
- [MyPy: using mypy with an existing codebase](https://mypy.readthedocs.io/en/stable/existing_code.html)
- [pytest configuration](https://docs.pytest.org/en/stable/reference/customize.html)
- [pytest-asyncio configuration](https://pytest-asyncio.readthedocs.io/en/stable/reference/configuration.html)
- [FastAPI async](https://fastapi.tiangolo.com/async/)
- [FastAPI response models](https://fastapi.tiangolo.com/tutorial/response-model/)
- [Google Gen AI SDK](https://googleapis.github.io/python-genai/)
