import asyncio

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import List, Dict, Set
import logging
import time

from ..database import get_db
from ..k8s_client_kubectl import K8sClient
from ..models import ActionLog, TrackedVariable, VariableServiceMapping
from ..schemas import ServiceEnvVars, UpdateRequest, ActionLogResponse
from ..config import Config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/services", tags=["services"])

k8s = K8sClient(Config.K8S_NAMESPACE, Config.K8S_KUBECONFIG)

active_connections: List[WebSocket] = []

async def notify_clients(message: dict):
    """Отправить уведомление всем подключенным клиентам"""
    for connection in active_connections[:]:
        try:
            # Не ждём ответа
            asyncio.create_task(connection.send_json(message))
        except:
            if connection in active_connections:
                active_connections.remove(connection)

def get_tracked_var_names(db: Session) -> Set[str]:
    vars = db.query(TrackedVariable).filter(TrackedVariable.enabled == True).all()
    return {v.name for v in vars}

def process_data(all_data: Dict[str, Dict[str, str]], tracked_names: Set[str]) -> List[ServiceEnvVars]:
    """Преобразует данные из kubectl в формат ответа"""
    result = []
    for name, env_vars in all_data.items():
        tracked_vars = {k: v for k, v in env_vars.items() if k in tracked_names}
        result.append(ServiceEnvVars(
            name=name,
            env_vars=env_vars,
            tracked_vars=tracked_vars
        ))
    return result

@router.get("/", response_model=List[ServiceEnvVars])
async def get_services(db: Session = Depends(get_db)):
    start = time.time()
    logger.info("📥 GET /api/services/ START")
    
    # ОДИН запрос к kubectl
    all_data = k8s.get_all_deployments_data()
    logger.info(f"   Got {len(all_data)} deployments in {time.time() - start:.2f}s")
    
    tracked_names = get_tracked_var_names(db)
    result = process_data(all_data, tracked_names)
    
    logger.info(f"✅ GET /api/services/ TOTAL: {time.time() - start:.2f}s")
    return result

@router.post("/update")
async def update_env_var(request: UpdateRequest, db: Session = Depends(get_db)):
    """Обновить переменную в сервисе (асинхронно)"""
    if not request.confirmed:
        raise HTTPException(status_code=400, detail="Action not confirmed")
    
    tracked = db.query(TrackedVariable).filter(TrackedVariable.name == request.var_name).first()
    if not tracked:
        raise HTTPException(status_code=400, detail=f"Variable '{request.var_name}' is not tracked")
    
    # Асинхронное обновление - не ждём kubectl
    success, _ = k8s.update_env_var_async(request.service, request.var_name, request.value)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send update command")
    
    # Логируем
    log = ActionLog(
        user=request.user,
        service=request.service,
        var_name=request.var_name,
        old_value="",  # не запрашиваем
        new_value=request.value,
        source="api"
    )
    db.add(log)
    db.commit()
    
    # Отправляем уведомление через WebSocket
    await notify_clients({
        "type": "env_updated",
        "service": request.service,
        "var_name": request.var_name,
        "old_value": "",
        "new_value": request.value,
        "user": request.user
    })
    
    return {"status": "ok", "message": "Команда отправлена, изменение применяется..."}

@router.get("/logs", response_model=List[ActionLogResponse])
async def get_logs(limit: int = 100, db: Session = Depends(get_db)):
    logs = db.query(ActionLog).order_by(ActionLog.timestamp.desc()).limit(limit).all()
    return logs

@router.get("/logs/{service}", response_model=List[ActionLogResponse])
async def get_service_logs(service: str, limit: int = 50, db: Session = Depends(get_db)):
    logs = db.query(ActionLog)\
        .filter(ActionLog.service == service)\
        .order_by(ActionLog.timestamp.desc())\
        .limit(limit).all()
    return logs

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)