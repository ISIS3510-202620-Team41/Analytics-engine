"""Cada archivo de este paquete es una feature con su propio `router`.

main.py los descubre solos: agregar una feature = agregar un archivo, sin tocar nada compartido.
Si el modulo define `summary_key` y `summary(conn, filters)`, /metrics/summary tambien lo incluye.
"""
import importlib
import pkgutil


def feature_modules():
    for info in pkgutil.iter_modules(__path__):
        yield importlib.import_module(f"{__name__}.{info.name}")