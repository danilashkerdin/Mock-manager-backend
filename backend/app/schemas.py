from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime

# ============ Tracked Variables ============
class VariableServiceMappingCreate(BaseModel):
    service_name: str

class TrackedVariableCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    services: List[str] = []  # список сервисов, где отслеживать эту переменную

class TrackedVariableResponse(BaseModel):
    id: int
    name: str
    description: str
    enabled: bool
    services: List[str] = []  # сервисы, где отслеживается
    created_at: datetime

# ============ Services ============
class ServiceEnvVars(BaseModel):
    name: str
    env_vars: Dict[str, str]  # все переменные
    tracked_vars: Dict[str, str]  # только отслеживаемые (из TrackedVariable)

class UpdateRequest(BaseModel):
    service: str
    var_name: str
    value: str
    user: str
    confirmed: bool = False

# ============ Groups ============
class GroupServiceMappingCreate(BaseModel):
    service_name: str
    var_name: str

class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    services: List[GroupServiceMappingCreate] = []  # теперь необязательное поле

class GroupResponse(BaseModel):
    id: str
    name: str
    description: str
    services: List[GroupServiceMappingCreate]
    enabled: Optional[Dict[str, bool]] = None  # статус для каждого сервиса
    created_at: datetime
    updated_at: Optional[datetime] = None

class GroupUpdateRequest(BaseModel):
    group_id: str
    enabled: bool  # true/false для всех сервисов в группе
    user: str
    confirmed: bool = False

# ============ Logs ============
class ActionLogResponse(BaseModel):
    id: int
    timestamp: datetime
    user: str
    service: str
    var_name: str
    old_value: str
    new_value: str
    source: str

# ============ Notifications ============
class NotificationChannelCreate(BaseModel):
    name: str
    type: str  # slack, band, webhook
    webhook_url: str
    events: List[str] = ["all"]

# ============ WebSocket ============
class WSMessage(BaseModel):
    type: str  # env_updated, group_updated, change_detected, tracked_vars_updated
    data: Dict