from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import logging

from ..database import get_db
from ..models import TrackedVariable, VariableServiceMapping
from ..schemas import TrackedVariableCreate, TrackedVariableResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/variables", tags=["variables"])

@router.get("/", response_model=List[TrackedVariableResponse])
async def get_tracked_variables(db: Session = Depends(get_db)):
    """Получить список отслеживаемых переменных с их сервисами"""
    variables = db.query(TrackedVariable).order_by(TrackedVariable.name).all()
    
    result = []
    for var in variables:
        # Получаем сервисы для этой переменной
        mappings = db.query(VariableServiceMapping).filter(
            VariableServiceMapping.variable_name == var.name
        ).all()
        services = [m.service_name for m in mappings]
        
        result.append(TrackedVariableResponse(
            id=var.id,
            name=var.name,
            description=var.description,
            enabled=var.enabled,
            services=services,
            created_at=var.created_at
        ))
    
    return result

@router.post("/", response_model=TrackedVariableResponse)
async def add_tracked_variable(
    var: TrackedVariableCreate, 
    db: Session = Depends(get_db)
):
    """Добавить переменную для отслеживания в указанных сервисах"""
    existing = db.query(TrackedVariable).filter(TrackedVariable.name == var.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Variable already tracked")
    
    # Создаём переменную
    db_var = TrackedVariable(
        name=var.name,
        description=var.description,
        enabled=True
    )
    db.add(db_var)
    db.flush()
    
    # Добавляем маппинги для сервисов
    for service_name in var.services:
        mapping = VariableServiceMapping(
            variable_name=var.name,
            service_name=service_name
        )
        db.add(mapping)
    
    db.commit()
    db.refresh(db_var)
    
    # Обновляем watcher
    from ..main import update_watcher_tracked_vars
    update_watcher_tracked_vars(db)
    
    return TrackedVariableResponse(
        id=db_var.id,
        name=db_var.name,
        description=db_var.description,
        enabled=db_var.enabled,
        services=var.services,
        created_at=db_var.created_at
    )

@router.put("/{var_id}")
async def update_variable_services(
    var_id: int,
    services: List[str],
    db: Session = Depends(get_db)
):
    """Обновить список сервисов для переменной"""
    var = db.query(TrackedVariable).filter(TrackedVariable.id == var_id).first()
    if not var:
        raise HTTPException(status_code=404, detail="Variable not found")
    
    # Удаляем старые маппинги
    db.query(VariableServiceMapping).filter(
        VariableServiceMapping.variable_name == var.name
    ).delete()
    
    # Добавляем новые
    for service_name in services:
        mapping = VariableServiceMapping(
            variable_name=var.name,
            service_name=service_name
        )
        db.add(mapping)
    
    db.commit()
    
    # Обновляем watcher
    from ..main import update_watcher_tracked_vars
    update_watcher_tracked_vars(db)
    
    return {"status": "ok", "services": services}

@router.delete("/{var_id}")
async def delete_tracked_variable(var_id: int, db: Session = Depends(get_db)):
    """Удалить переменную из отслеживания"""
    var = db.query(TrackedVariable).filter(TrackedVariable.id == var_id).first()
    if not var:
        raise HTTPException(status_code=404, detail="Variable not found")
    
    # Удаляем маппинги
    db.query(VariableServiceMapping).filter(
        VariableServiceMapping.variable_name == var.name
    ).delete()
    
    # Удаляем переменную
    db.delete(var)
    db.commit()
    
    # Обновляем watcher
    from ..main import update_watcher_tracked_vars
    update_watcher_tracked_vars(db)
    
    return {"status": "ok"}

@router.patch("/{var_id}/toggle")
async def toggle_tracked_variable(var_id: int, db: Session = Depends(get_db)):
    """Включить/выключить отслеживание переменной"""
    var = db.query(TrackedVariable).filter(TrackedVariable.id == var_id).first()
    if not var:
        raise HTTPException(status_code=404, detail="Variable not found")
    
    var.enabled = not var.enabled
    db.commit()
    
    # Обновляем watcher
    from ..main import update_watcher_tracked_vars
    update_watcher_tracked_vars(db)
    
    return {"status": "ok", "enabled": var.enabled}