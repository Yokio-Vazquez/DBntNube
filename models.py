from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, BigInteger, CheckConstraint, Numeric
from sqlalchemy.sql import func
from .database import Base

class Game(Base):
    __tablename__ = "games"

    id = Column(BigInteger, primary_key=True, index=True)
    title = Column(String(150), unique=True, nullable=False)
    genre = Column(String(50), nullable=False)
    classification = Column(String(20), nullable=False)
    description = Column(String, nullable=False)
    release_date = Column(DateTime, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class GameMetric(Base):
    __tablename__ = "game_metrics"

    id = Column(BigInteger, primary_key=True, index=True)
    external_id = Column(String(100), unique=True, nullable=False)
    game_id = Column(BigInteger, ForeignKey("games.id", ondelete="RESTRICT"), nullable=False, index=True)
    metric_name = Column(String(30), nullable=False)
    metric_value = Column(Numeric(10, 2), nullable=False)
    unit = Column(String(20), nullable=False)
    measured_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
