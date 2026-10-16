"""Routes de l'API locale."""

from fastapi import Request


def rf(request: Request):
    """État partagé de l'application (configuration, bases, services)."""
    return request.app.state.rf
