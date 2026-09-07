from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, OperationalError
from .database import get_db
from .models import GameMetric

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
