from fastapi import APIRouter

from metrics.plan_creation_success import calculate_plan_creation_success

router = APIRouter()


@router.get("/metrics/plan-creation-success")
def get_plan_creation_success():
    """Devuelve las combinaciones de contexto y su tasa de exito."""
    return calculate_plan_creation_success()
