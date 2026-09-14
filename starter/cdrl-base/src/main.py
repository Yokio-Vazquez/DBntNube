from fastapi import FastAPI, HTTPException, Depends, Query
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy import func, select
from .database import get_db
from .models import Game, GameMetric

app = FastAPI(title="CDRL API - Métricas de Videojuegos")

class GameMetricBase(BaseModel):
    model_config = ConfigDict(extra='forbid')
    
    external_id: str = Field(..., description="Identificador único externo de la métrica")
    game_id: int = Field(..., description="ID interno del videojuego")
    metric_name: str = Field(..., description="Nombre de la métrica (duration o rating)")
    metric_value: float = Field(..., description="Valor de la métrica")
    unit: str = Field(..., description="Unidad de medida (hours o stars)")
    measured_at: datetime = Field(..., description="Fecha y hora de registro en formato ISO 8601")

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "API CDRL funcionando correctamente"}

def metric_to_dict(metric: GameMetric):
    return {
        "id": metric.id,
        "external_id": metric.external_id,
        "game_id": metric.game_id,
        "metric_name": metric.metric_name,
        "metric_value": float(metric.metric_value),
        "unit": metric.unit,
        "measured_at": metric.measured_at,
    }

@app.get("/metrics")
def get_metrics(
    game_id: int | None = Query(default=None),
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
):
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="El parámetro from debe ser anterior o igual a to.")

    query = select(GameMetric)
    if game_id is not None:
        query = query.where(GameMetric.game_id == game_id)
    if from_date is not None:
        query = query.where(GameMetric.measured_at >= from_date)
    if to_date is not None:
        query = query.where(GameMetric.measured_at <= to_date)

    metrics = db.scalars(query.order_by(GameMetric.measured_at, GameMetric.id)).all()
    return [metric_to_dict(metric) for metric in metrics]

@app.get("/metrics/by-value")
def get_metrics_by_value(
    metric_name: str = Query(..., min_length=1),
    min_value: float = Query(..., ge=0),
    db: Session = Depends(get_db),
):
    query = (
        select(GameMetric)
        .where(
            GameMetric.metric_name == metric_name,
            GameMetric.metric_value >= min_value,
        )
        .order_by(GameMetric.metric_value.desc(), GameMetric.id)
    )
    metrics = db.scalars(query).all()
    return [metric_to_dict(metric) for metric in metrics]

@app.get("/metrics/summary")
def get_rating_summary(db: Session = Depends(get_db)):
    query = (
        select(
            Game.id.label("game_id"),
            Game.title.label("game_title"),
            func.avg(GameMetric.metric_value).label("average_rating"),
            func.count(GameMetric.id).label("metric_count"),
        )
        .join(GameMetric, GameMetric.game_id == Game.id)
        .where(GameMetric.metric_name == "rating")
        .group_by(Game.id, Game.title)
        .order_by(Game.id)
    )
    return [
        {
            "game_id": game_id,
            "game_title": game_title,
            "average_rating": float(average_rating) if isinstance(average_rating, Decimal) else average_rating,
            "metric_count": metric_count,
        }
        for game_id, game_title, average_rating, metric_count in db.execute(query).all()
    ]

@app.post("/metrics", status_code=201)
def create_metric(metric: GameMetricBase, db: Session = Depends(get_db)):
    try:
        new_metric = GameMetric(
            external_id=metric.external_id,
            game_id=metric.game_id,
            metric_name=metric.metric_name,
            metric_value=metric.metric_value,
            unit=metric.unit,
            measured_at=metric.measured_at
        )
        db.add(new_metric)
        db.commit()
        db.refresh(new_metric)
        
        return {
            "status": "success",
            "message": "Métrica guardada correctamente",
            "data": metric.model_dump(mode='json')
        }
    except IntegrityError as e:
        db.rollback()
        error_msg = str(e.orig).lower()
        if "game_metrics_game_fk" in error_msg or "foreign key constraint" in error_msg:
            raise HTTPException(
                status_code=422, 
                detail=f"Unprocessable Entity: El videojuego con game_id={metric.game_id} no existe."
            )
        elif "game_metrics_external_id_unique" in error_msg or "unique constraint" in error_msg:
            raise HTTPException(
                status_code=409, 
                detail="Conflict: Ya existe una métrica con este external_id."
            )
        else:
            raise HTTPException(
                status_code=422,
                detail=f"Unprocessable Entity: Violación de restricción de datos. {e.orig}"
            )
    except OperationalError:
        db.rollback()
        raise HTTPException(
            status_code=503, 
            detail="Service Unavailable: No se pudo conectar a la base de datos."
        )
