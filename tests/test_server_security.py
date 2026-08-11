"""Security contract tests for public HTTP endpoints."""

from fastapi.routing import APIRoute

from agent.server.app import app, require_api_key


def _route(path: str, method: str) -> APIRoute:
    return next(
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )


def test_chat_endpoints_require_api_key_dependency():
    for path in ("/chat", "/chat/stream"):
        dependencies = [item.call for item in _route(path, "POST").dependant.dependencies]
        assert require_api_key in dependencies
