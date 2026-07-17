import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict
import logging

from ..database import get_db
from ..models import Group as GroupModel, GroupServiceMapping, ActionLog, TrackedVariable
from ..schemas import GroupCreate, GroupResponse, GroupUpdateRequest, GroupServiceMappingCreate
from ..k8s_client_kubectl import K8sClient
from ..config import Config
from .services import k8s, notify_clients

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/groups", tags=["groups"])

import time

@router.get("/", response_model=List[GroupResponse])
async def get_groups(db: Session = Depends(get_db)):
    groups = db.query(GroupModel).all()
    
    result = []
    for group in groups:
        mappings = db.query(GroupServiceMapping).filter(
            GroupServiceMapping.group_id == group.id
        ).all()
        
        services = [
            GroupServiceMappingCreate(
                service_name=m.service_name,
                var_name=m.var_name
            )
            for m in mappings
        ]
        
        result.append(GroupResponse(
            id=group.id,
            name=group.name,
            description=group.description or "",
            services=services,
            enabled=None,  # ← Убираем запрос к K8s
            created_at=group.created_at,
            updated_at=group.updated_at
        ))
    
    return result

@router.get("/{group_id}/status")
async def get_group_status(group_id: str, db: Session = Depends(get_db)):
    """Получить статус группы (отдельный быстрый запрос)"""
    mappings = db.query(GroupServiceMapping).filter(
        GroupServiceMapping.group_id == group_id
    ).all()
    
    enabled_status = {}
    for mapping in mappings:
        env_vars = k8s.get_deployment_env_vars(mapping.service_name)
        val = env_vars.get(mapping.var_name)
        if val is not None:
            enabled_status[mapping.service_name] = val.lower() == "true"
    
    return enabled_status

@router.post("/", response_model=GroupResponse)
async def create_group(group: GroupCreate, db: Session = Depends(get_db)):
    """Создать новую группу (можно без сервисов)"""
    
    group_id = str(uuid.uuid4())
    
    db_group = GroupModel(
        id=group_id,
        name=group.name,
        description=group.description,
    )
    db.add(db_group)
    
    # Добавляем сервисы, если они есть
    for service_mapping in group.services:
        var = db.query(TrackedVariable).filter(
            TrackedVariable.name == service_mapping.var_name
        ).first()
        if not var:
            raise HTTPException(
                status_code=400, 
                detail=f"Variable '{service_mapping.var_name}' is not tracked"
            )
        
        mapping = GroupServiceMapping(
            group_id=group_id,
            service_name=service_mapping.service_name,
            var_name=service_mapping.var_name
        )
        db.add(mapping)
    
    db.commit()
    
    return GroupResponse(
        id=db_group.id,
        name=db_group.name,
        description=db_group.description or "",
        services=group.services,
        enabled=None,
        created_at=db_group.created_at,
        updated_at=db_group.updated_at
    )

@router.post("/update")
async def update_group(request: GroupUpdateRequest, db: Session = Depends(get_db)):
    """Обновить все сервисы в группе"""
    if not request.confirmed:
        raise HTTPException(status_code=400, detail="Action not confirmed")
    
    group = db.query(GroupModel).filter(GroupModel.id == request.group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    mappings = db.query(GroupServiceMapping).filter(
        GroupServiceMapping.group_id == request.group_id
    ).all()
    
    value = "true" if request.enabled else "false"
    updated_services = []
    errors = []
    
    for mapping in mappings:
        old_vars = k8s.get_deployment_env_vars(mapping.service_name)
        old_value = old_vars.get(mapping.var_name, "")
        
        success, _ = k8s.update_env_var(
            mapping.service_name, 
            mapping.var_name, 
            value
        )
        
        if success:
            updated_services.append({
                "service": mapping.service_name,
                "var_name": mapping.var_name,
                "old_value": old_value,
                "new_value": value
            })
            
            # Логируем
            log = ActionLog(
                user=request.user,
                service=mapping.service_name,
                var_name=mapping.var_name,
                old_value=old_value,
                new_value=value,
                source="group"
            )
            db.add(log)
        else:
            errors.append(f"{mapping.service_name}.{mapping.var_name}")
    
    db.commit()
    
    # Уведомляем через WebSocket
    await notify_clients({
        "type": "group_updated",
        "group_id": group.id,
        "group_name": group.name,
        "enabled": request.enabled,
        "updated_services": updated_services,
        "errors": errors,
        "user": request.user
    })
    
    return {
        "status": "ok",
        "updated_services": updated_services,
        "errors": errors,
        "total": len(mappings)
    }

@router.delete("/{group_id}")
async def delete_group(group_id: str, db: Session = Depends(get_db)):
    """Удалить группу вместе с маппингами"""
    group = db.query(GroupModel).filter(GroupModel.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    # Удаляем маппинги
    db.query(GroupServiceMapping).filter(
        GroupServiceMapping.group_id == group_id
    ).delete()
    
    # Удаляем группу
    db.delete(group)
    db.commit()
    
    return {"status": "ok"}

@router.post("/{group_id}/services")
async def add_service_to_group(
    group_id: str,
    service_mapping: GroupServiceMappingCreate,
    db: Session = Depends(get_db)
):
    """Добавить сервис с переменной в существующую группу"""
    
    group = db.query(GroupModel).filter(GroupModel.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    # Проверяем, что переменная отслеживается
    var = db.query(TrackedVariable).filter(
        TrackedVariable.name == service_mapping.var_name
    ).first()
    if not var:
        raise HTTPException(
            status_code=400, 
            detail=f"Variable '{service_mapping.var_name}' is not tracked"
        )
    
    # Проверяем, не существует ли уже такой маппинг
    existing = db.query(GroupServiceMapping).filter(
        GroupServiceMapping.group_id == group_id,
        GroupServiceMapping.service_name == service_mapping.service_name,
        GroupServiceMapping.var_name == service_mapping.var_name
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Mapping already exists")
    
    mapping = GroupServiceMapping(
        group_id=group_id,
        service_name=service_mapping.service_name,
        var_name=service_mapping.var_name
    )
    db.add(mapping)
    db.commit()
    
    return {"status": "ok", "service": service_mapping.service_name, "var": service_mapping.var_name}


@router.delete("/{group_id}/services")
async def remove_service_from_group(
    group_id: str,
    service_name: str,
    var_name: str,
    db: Session = Depends(get_db)
):
    """Удалить сервис из группы"""
    
    mapping = db.query(GroupServiceMapping).filter(
        GroupServiceMapping.group_id == group_id,
        GroupServiceMapping.service_name == service_name,
        GroupServiceMapping.var_name == var_name
    ).first()
    
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    
    db.delete(mapping)
    db.commit()
    
    return {"status": "ok"}