from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, BigInteger, CheckConstraint, Numeric, Date
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

    __table_args__ = (
        CheckConstraint('metric_value >= 0', name='check_metric_value_positive'),
    )

class Platform(Base):
    __tablename__ = "platforms"

    id = Column(BigInteger, primary_key=True, index=True)
    code = Column(String(30), unique=True, nullable=False)
    name = Column(String(80), nullable=False)
    manufacturer = Column(String(80), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class GamePlatform(Base):
    __tablename__ = "game_platforms"

    game_id = Column(BigInteger, ForeignKey("games.id", ondelete="CASCADE"), primary_key=True)
    platform_id = Column(BigInteger, ForeignKey("platforms.id", ondelete="RESTRICT"), primary_key=True)
    release_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, server_default="available")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('planned', 'available', 'retired')", name='game_platforms_status_valid'),
        CheckConstraint("release_date >= '1970-01-01'", name='game_platforms_release_date_valid'),
    )

class MetricDefinition(Base):
    __tablename__ = "metric_definitions"

    id = Column(BigInteger, primary_key=True, index=True)
    metric_name = Column(String(30), unique=True, nullable=False)
    unit = Column(String(20), nullable=False)
    description = Column(String(200), nullable=False)

