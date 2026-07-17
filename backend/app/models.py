from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Boolean, UniqueConstraint
from sqlalchemy.sql import func
from .database import Base


class TrackedVariable(Base):
    """Отслеживаемые переменные"""
    __tablename__ = "tracked_variables"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String, default="")
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class VariableServiceMapping(Base):
    """Какие переменные в каких сервисах отслеживать"""
    __tablename__ = "variable_service_mappings"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    variable_name = Column(String, nullable=False)
    service_name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Уникальность: одна переменная в одном сервисе не может быть добавлена дважды
    __table_args__ = (
        UniqueConstraint('variable_name', 'service_name', name='unique_var_service'),
    )


class Group(Base):
    """Группы сервисов (без привязки к одной переменной)"""
    __tablename__ = "groups"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class GroupServiceMapping(Base):
    """Маппинг сервиса в группе с конкретным именем переменной"""
    __tablename__ = "group_service_mappings"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(String, nullable=False)
    service_name = Column(String, nullable=False)
    var_name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ActionLog(Base):
    """Лог изменений"""
    __tablename__ = "action_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    user = Column(String, nullable=False)
    service = Column(String, nullable=False)
    var_name = Column(String, nullable=False)
    old_value = Column(String, default="")
    new_value = Column(String, nullable=False)
    source = Column(String, default="api")  # api, watcher, manual, group


class NotificationChannel(Base):
    """Каналы уведомлений"""
    __tablename__ = "notification_channels"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # slack, band, webhook
    webhook_url = Column(String, nullable=False)
    enabled = Column(Boolean, default=True)
    events = Column(JSON, default=["all"])  # какие события: all, update, external_change