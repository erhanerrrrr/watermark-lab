"""HTTP adapter for the Watermark Lab research core."""

__all__ = ["app"]


def __getattr__(name: str):
    # A worker may import api utilities without constructing the HTTP application.
    if name == "app":
        from watermark_lab.api.app import app

        globals()["app"] = app
        return app
    raise AttributeError(name)
