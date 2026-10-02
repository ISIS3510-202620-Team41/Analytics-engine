"""Contrato de entrada: eventos validados con Pydantic y su conversion a fila de la base."""
from datetime import datetime, timedelta
from enum import Enum
from typing import Annotated, Literal, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from filters import to_db_time, to_utc

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

    @model_validator(mode="after")
    def _screen_required_for_screen_loads(self):
        if self.loadType == "screen" and not self.screen:
            raise ValueError("screen es obligatorio cuando loadType = 'screen'")
        return self


class ScreenViewEvent(_BaseEvent):
    eventType: Literal["screen_view"]
    screen: str = Field(min_length=1, max_length=100)


class CrashEvent(_BaseEvent):
    eventType: Literal["crash"]
    screen: str = Field(min_length=1, max_length=100)
    component: str | None = Field(default=None, max_length=100)   # ej. "btn_join"
    exceptionType: str | None = Field(default=None, max_length=200)


class RecommendationShownEvent(_BaseEvent):
    eventType: Literal["recommendation_shown"]
    recommendationId: str = Field(min_length=1, max_length=100)   # uno por carga de la lista
    freeTimeMinutes: int | None = Field(default=None, ge=0)


class RecommendedActivitySelectedEvent(_BaseEvent):
    """El usuario hizo join a una actividad que se le recomendo."""
    eventType: Literal["recommended_activity_selected"]
    activityId: str = Field(min_length=1, max_length=100)
    category: Category
    freeTimeMinutes: int | None = Field(default=None, ge=0)
    recommendationId: str | None = Field(default=None, max_length=100)

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class FriendAvailabilityUsedEvent(_BaseEvent):
    eventType: Literal["friend_availability_used"]
    action: Literal["viewed", "plan_created", "plan_joined"] = "viewed"
    activityId: str | None = Field(default=None, max_length=100)


AnalyticsEvent = Annotated[
    Union[
        AppLoadingTimeEvent,
        ScreenViewEvent,
        CrashEvent,
        RecommendationShownEvent,
        RecommendedActivitySelectedEvent,
        FriendAvailabilityUsedEvent,
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

    category = getattr(event, "category", None)
    if isinstance(category, Enum):
        category = category.value

    return {
        "event_id": str(event.eventId or uuid4()),
        "event_type": event.eventType,
        "user_id": str(event.userId),
        "session_id": event.sessionId,
        "app_version": event.appVersion,
        "occurred_at": to_db_time(occurred_at),
        "received_at": to_db_time(received_at),
        "screen": getattr(event, "screen", None),
        "component": getattr(event, "component", None),
        "exception_type": getattr(event, "exceptionType", None),
        "load_type": getattr(event, "loadType", None),
        "duration_ms": getattr(event, "durationMs", None),
        "activity_id": getattr(event, "activityId", None),
        "category": category,
        "free_time_minutes": getattr(event, "freeTimeMinutes", None),
        "recommendation_id": getattr(event, "recommendationId", None),
        "action": getattr(event, "action", None),
    }