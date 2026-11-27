"""Contrato de entrada: eventos validados con Pydantic y su conversion a fila de la base."""
from datetime import datetime, timedelta
from enum import Enum
from typing import Annotated, Literal, Union
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator

from filters import to_db_time, to_utc

NetworkQuality = Literal[
    "good",
    "fair",
    "poor",
    "offline",
    "unknown",
]

# Si el reloj del telefono va adelantado mas que esto, se usa la hora del servidor.
MAX_CLOCK_SKEW = timedelta(minutes=5)


class Category(str, Enum):
    """Espejo de com.group41.backend.activity.domain.Category. Mantener sincronizado con config.CATEGORIES."""
    DEPORTES = "DEPORTES"
    ESTUDIO = "ESTUDIO"
    CULTURA = "CULTURA"
    ENTRETENIMIENTO = "ENTRETENIMIENTO"


class _BaseEvent(BaseModel):
    # La app genera un UUID por evento: si reintenta el envio, el servidor lo descarta como duplicado.
    eventId: UUID | None = None
    # UUID del User del backend.
    userId: UUID
    sessionId: str | None = Field(default=None, max_length=100)
    # Eventos emitidos por el backend Spring no tienen version de app.
    appVersion: str | None = Field(default=None, max_length=50)
    # Momento en que ocurrio segun el cliente (opcional). El servidor siempre guarda ademas su propia hora.
    timestamp: datetime | None = None


class AppLoadingTimeEvent(_BaseEvent):
    eventType: Literal["app_loading_time"]
    loadType: Literal["cold_start", "warm_start", "screen"]
    screen: str | None = Field(default=None, max_length=100)
    durationMs: int = Field(ge=0, le=600_000)
    networkQuality: NetworkQuality = "unknown"

    @model_validator(mode="after")
    def _screen_required_for_screen_loads(self):
        if self.loadType == "screen" and not self.screen:
            raise ValueError("screen es obligatorio cuando loadType = 'screen'")
        return self

class PerformanceBenchmarkEvent(_BaseEvent):
    """Registra el rendimiento antes y después de una micro-optimización."""

    eventType: Literal["performance_benchmark"]

    benchmarkId: str = Field(min_length=1, max_length=100)

    optimizationStage: Literal["baseline", "optimized"]

    jankFrames: int = Field(ge=0)

    totalFrames: int = Field(gt=0)

    heapMemoryMb: float = Field(ge=0)

    @model_validator(mode="after")
    def _validate_jank_frames(self):
        if self.jankFrames > self.totalFrames:
            raise ValueError("jankFrames no puede superar totalFrames")
        return self

class ScreenViewEvent(_BaseEvent):
    eventType: Literal["screen_view"]
    screen: str = Field(min_length=1, max_length=100)

class FeatureUsedEvent(_BaseEvent):
    eventType: Literal["feature_used"]

    # Identificador, por ejemplo "friend_availability".
    feature: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_]*$",
    )

    # Acción concreta dentro de la funcionalidad, si aplica.
    action: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_]*$",
    )

    # Pantalla desde la que se utilizó la funcionalidad.
    screen: str | None = Field(default=None, max_length=100)

    @field_validator("feature", "action", mode="before")
    @classmethod
    def _normalize_identifiers(cls, value):
        return value.strip() if isinstance(value, str) else value


class CrashEvent(_BaseEvent):
    eventType: Literal["crash"]
    screen: str = Field(min_length=1, max_length=100)
    component: str | None = Field(default=None, max_length=100)   # ej. "btn_join"
    exceptionType: str | None = Field(default=None, max_length=200)


class RecommendationShownEvent(_BaseEvent):
    eventType: Literal["recommendation_shown"]
    recommendationId: str = Field(min_length=1, max_length=100)   # uno por carga de la lista
    freeTimeMinutes: int | None = Field(default=None, ge=0)
    networkQuality: NetworkQuality = "unknown"


class RecommendedActivitySelectedEvent(_BaseEvent):
    """El usuario hizo join a una actividad que se le recomendo."""
    eventType: Literal["recommended_activity_selected"]
    activityId: str = Field(min_length=1, max_length=100)
    category: Category
    freeTimeMinutes: int | None = Field(default=None, ge=0)
    recommendationId: str | None = Field(default=None, max_length=100)
    networkQuality: NetworkQuality = "unknown"
    title: str | None = Field(default=None, max_length=200)
    price: str | None = Field(default=None, max_length=50)
    activityDurationMinutes: int | None = Field(default=None, ge=0)

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class FriendAvailabilityUsedEvent(_BaseEvent):
    eventType: Literal["friend_availability_used"]
    action: Literal["viewed", "plan_created", "plan_joined", "matrix_viewed", "create_plan"] = "viewed"
    activityId: str | None = Field(default=None, max_length=100)


class ActivityEnrollmentConfirmedEvent(_BaseEvent):
    """Registra una inscripcion confirmada por el backend."""

    eventType: Literal["activity_enrollment_confirmed"]
    activityId: str = Field(min_length=1, max_length=100)
    # La hora programada debe incluir la zona horaria o el desplazamiento UTC.
    scheduledStartTime: AwareDatetime
    # Identifica la misma inscripcion en la confirmacion y la cancelacion.
    enrollmentId: UUID


class ActivityEnrollmentCanceledEvent(_BaseEvent):
    """Registra la cancelacion confirmada de una inscripcion."""

    eventType: Literal["activity_enrollment_canceled"]
    activityId: str = Field(min_length=1, max_length=100)
    # La hora programada permite calcular la antelacion de la cancelacion.
    scheduledStartTime: AwareDatetime
    # Identifica la misma inscripcion en la confirmacion y la cancelacion.
    enrollmentId: UUID


class PlanCreationAttemptedEvent(_BaseEvent):
    """Contexto disponible cuando el usuario intenta crear un plan."""

    eventType: Literal["plan_creation_attempted"]
    attemptId: UUID

    # Snapshot de las preferencias seleccionadas para este intento.
    preferences: list[str] = Field(default_factory=list, max_length=20)

    freeTimeMinutes: int = Field(ge=0)

    locationName: str = Field(min_length=1, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    availableFriendsCount: int = Field(ge=0)
    selectedAvailableFriendsCount: int = Field(ge=0)

    @field_validator("preferences", mode="before")
    @classmethod
    def _normalize_preferences(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("preferences debe ser una lista")
        return [
            item.strip().upper()
            for item in value
            if isinstance(item, str) and item.strip()
        ]

    @field_validator("locationName", mode="before")
    @classmethod
    def _normalize_location_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _validate_friend_counts(self):
        if self.selectedAvailableFriendsCount > self.availableFriendsCount:
            raise ValueError(
                "selectedAvailableFriendsCount no puede superar "
                "availableFriendsCount"
            )

        if (self.latitude is None) != (self.longitude is None):
            raise ValueError(
                "latitude y longitude deben enviarse juntas"
            )

        return self


class PlanCreationResultEvent(_BaseEvent):
    """Resultado definitivo de un intento de creacion."""

    eventType: Literal["plan_creation_result"]
    attemptId: UUID

    status: Literal["success", "failure"]
    planId: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def _validate_plan_id(self):
        if self.status == "success" and not self.planId:
            raise ValueError("planId es obligatorio cuando status = 'success'")

        if self.status == "failure" and self.planId is not None:
            raise ValueError("planId debe ser null cuando status = 'failure'")

        return self


AnalyticsEvent = Annotated[
    Union[
        AppLoadingTimeEvent,
        ScreenViewEvent,
        FeatureUsedEvent,
        CrashEvent,
        RecommendationShownEvent,
        PerformanceBenchmarkEvent,
        RecommendedActivitySelectedEvent,
        FriendAvailabilityUsedEvent,
        # Inscripciones y cancelaciones confirmadas para BQ12.
        ActivityEnrollmentConfirmedEvent,
        ActivityEnrollmentCanceledEvent,
        PlanCreationAttemptedEvent,
        PlanCreationResultEvent,
    ],
    Field(discriminator="eventType"),
]


class EventBatch(BaseModel):
    events: list[AnalyticsEvent] = Field(min_length=1, max_length=500)


class IngestResponse(BaseModel):
    accepted: int
    duplicates: int


def to_row(event, received_at: datetime) -> dict:
    """Convierte un evento validado en la fila de la tabla `events`."""
    received_at = to_utc(received_at)
    occurred_at = received_at
    if event.timestamp is not None:
        claimed = to_utc(event.timestamp)
        occurred_at = claimed if claimed <= received_at + MAX_CLOCK_SKEW else received_at

    # Los eventos anteriores no tienen una hora de inicio programada.
    scheduled_start = getattr(event, "scheduledStartTime", None)
    enrollment_id = getattr(event, "enrollmentId", None)

    category = getattr(event, "category", None)
    if isinstance(category, Enum):
        category = category.value

    attempt_id = getattr(event, "attemptId", None)
    preferences = getattr(event, "preferences", None)

    if preferences is not None:
        import json
        preferences = json.dumps(preferences, ensure_ascii=False)

    return {
        "event_id": str(event.eventId or uuid4()),
        "event_type": event.eventType,
        "user_id": str(event.userId),
        "session_id": event.sessionId,
        "app_version": event.appVersion,
        "occurred_at": to_db_time(occurred_at),
        "received_at": to_db_time(received_at),
        "scheduled_start_time": to_db_time(scheduled_start) if scheduled_start is not None else None,
        "screen": getattr(event, "screen", None),
        "feature": getattr(event, "feature", None),
        "component": getattr(event, "component", None),
        "exception_type": getattr(event, "exceptionType", None),
        "load_type": getattr(event, "loadType", None),
        "duration_ms": getattr(event, "durationMs", None),
        "activity_id": getattr(event, "activityId", None),
        "enrollment_id": str(enrollment_id) if enrollment_id is not None else None,
        "category": category,
        "free_time_minutes": getattr(event, "freeTimeMinutes", None),
        "recommendation_id": getattr(event, "recommendationId", None),
        "action": getattr(event, "action", None),
        "network_quality": getattr( event, "networkQuality", "unknown"),
        "title": getattr(event, "title", None),
        "price": getattr(event, "price", None),
        "activity_duration_minutes": getattr(event, "activityDurationMinutes", None),
        "benchmark_id": getattr(event, "benchmarkId", None),
        "optimization_stage": getattr(event, "optimizationStage", None),
        "jank_frames": getattr(event, "jankFrames", None),
        "total_frames": getattr(event, "totalFrames", None),
        "heap_memory_mb": getattr(event, "heapMemoryMb", None),
    }
        "attempt_id": str(attempt_id) if attempt_id is not None else None,
        "preferences": preferences,
        "location_name": getattr(event, "locationName", None),
        "latitude": getattr(event, "latitude", None),
        "longitude": getattr(event, "longitude", None),
        "available_friends_count": getattr(event, "availableFriendsCount", None),
        "selected_available_friends_count": getattr(event, "selectedAvailableFriendsCount", None),
        "creation_status": getattr(event, "status", None),
        "plan_id": getattr(event, "planId", None),
    }
