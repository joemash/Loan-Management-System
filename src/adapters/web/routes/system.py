"""OpenAPI groups, Swagger UI and actuator-style health/metrics endpoints."""

import json

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import Engine

from src.adapters.repositories.database import ping
from src.infrastructure.config.settings import Settings

API_GROUPS = {"admin": ("/admin/",), "core": ("/loans/", "/customers/")}


def register_docs(app: FastAPI) -> None:
    def group_spec(prefixes: tuple[str, ...]) -> dict:
        spec = dict(app.openapi())
        spec["paths"] = {p: v for p, v in spec["paths"].items() if p.startswith(prefixes)}
        return spec

    for group, prefixes in API_GROUPS.items():
        app.add_api_route(
            f"/api-docs/{group}",
            lambda prefixes=prefixes: JSONResponse(group_spec(prefixes)),
            include_in_schema=False,
        )

    config = {
        # "all" first and selected by default so every endpoint is visible; admin/core narrow the view.
        "urls": [{"name": "all", "url": "/api-docs"}]
        + [{"name": g, "url": f"/api-docs/{g}"} for g in API_GROUPS],
        "urls.primaryName": "all",
        "dom_id": "#swagger-ui",
        "deepLinking": True,
        "operationsSorter": "method",
        "tagsSorter": "alpha",
        "tryItOutEnabled": True,
        "persistAuthorization": True,
    }
    html = _SWAGGER_UI_HTML.replace("__CONFIG__", json.dumps(config))

    # FastAPI's get_swagger_ui_html() omits swagger-ui-standalone-preset.js, which provides the
    # StandaloneLayout top bar used for the admin/core group selector, so the page is rendered here.
    @app.get("/swagger-ui", include_in_schema=False)
    def swagger_ui():
        return HTMLResponse(html)


_SWAGGER_UI_DIST = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5"
_SWAGGER_UI_HTML = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>LMS API - Swagger UI</title>
  <link rel="stylesheet" href="{_SWAGGER_UI_DIST}/swagger-ui.css">
  <link rel="icon" href="https://fastapi.tiangolo.com/img/favicon.png">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="{_SWAGGER_UI_DIST}/swagger-ui-bundle.js"></script>
  <script src="{_SWAGGER_UI_DIST}/swagger-ui-standalone-preset.js"></script>
  <script>
    window.ui = SwaggerUIBundle(Object.assign(__CONFIG__, {{
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
      plugins: [SwaggerUIBundle.plugins.DownloadUrl],
      layout: "StandaloneLayout",
    }}));
  </script>
</body>
</html>
"""


def register_actuator(app: FastAPI) -> None:
    def db_up() -> bool:
        return ping(app.state.injector.get(Engine))

    @app.get("/actuator/health", tags=["actuator"])
    def health():
        up = db_up()
        body = {"status": "UP" if up else "DOWN", "components": {"db": {"status": "UP" if up else "DOWN"}}}
        return JSONResponse(body, status_code=200 if up else 503)

    @app.get("/actuator/health/liveness", tags=["actuator"])
    def liveness():
        return {"status": "UP"}

    @app.get("/actuator/health/readiness", tags=["actuator"])
    def readiness():
        return health()

    @app.get("/actuator/info", tags=["actuator"])
    def info():
        return {"app": {"name": app.state.injector.get(Settings).app_name}}

    @app.get("/actuator/prometheus", tags=["actuator"])
    def prometheus():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
