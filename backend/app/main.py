import asyncio
import threading
import time
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session
import logging
from typing import Set

from .config import Config
from .database import engine, Base, SessionLocal
from .api import services, groups, variables
from .k8s_watcher import K8sWatcher
from .notifiers.slack import SlackNotifier
from .notifiers.band import BandNotifier
from .models import TrackedVariable

startup_time = time.time()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Отключаем слишком verbose логи от библиотек
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# Создаем таблицы
Base.metadata.create_all(bind=engine)

# Глобальные объекты
watcher = None
slack_notifier = None
band_notifier = None
_loop = None  # Храним ссылку на event loop

def get_tracked_vars_from_db(db: Session) -> dict[str, Set[str]]:
    """Получить список отслеживаемых переменных с их сервисами
    Returns: {variable_name: {service_name1, service_name2, ...}}
    """
    from .models import TrackedVariable, VariableServiceMapping
    
    result = {}
    variables = db.query(TrackedVariable).filter(TrackedVariable.enabled == True).all()
    
    for var in variables:
        # Получаем сервисы для этой переменной
        mappings = db.query(VariableServiceMapping).filter(
            VariableServiceMapping.variable_name == var.name
        ).all()
        
        # Преобразуем в множество
        services = {m.service_name for m in mappings}
        result[var.name] = services
        
        logger.info(f"Variable '{var.name}' will be tracked in services: {services if services else 'ALL'}")
    
    return result

def update_watcher_tracked_vars(db: Session):
    """Обновить список отслеживаемых переменных в watcher"""
    global watcher
    if watcher:
        tracked_vars_map = get_tracked_vars_from_db(db)
        watcher.update_tracked_vars(tracked_vars_map)
        logger.info(f"Watcher tracked vars updated: {tracked_vars_map}")

def run_async(coro):
    """Безопасно запустить асинхронную корутину из синхронного кода"""
    global _loop
    if _loop and _loop.is_running():
        # Если event loop уже запущен, создаем task
        asyncio.run_coroutine_threadsafe(coro, _loop)
    else:
        # Иначе запускаем новый event loop (для тестов)
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(coro)
        finally:
            loop.close()

def on_k8s_change(change: dict):
    """Обработчик изменений от watcher"""

    if time.time() - startup_time < 10:
        logger.debug(f"Skipping notification during startup: {change}")
        return
    
    logger.info(f"K8s change detected: {change}")
    
    # Формируем сообщение
    message = (
        f"Service: {change['service']}\n"
        f"Variable: {change['var_name']}\n"
        f"Changed from `{change['old_value']}` to `{change['new_value']}`\n"
        f"Source: {change['source']}"
    )
    
    # Отправляем уведомления (синхронно, чтобы не было проблем с event loop)
    if slack_notifier:
        try:
            # Запускаем в отдельном потоке, чтобы не блокировать
            threading.Thread(
                target=lambda: asyncio.run(slack_notifier.send(message=message, title="🔄 Variable Changed")),
                daemon=True
            ).start()
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
    
    if band_notifier:
        try:
            threading.Thread(
                target=lambda: asyncio.run(band_notifier.send(message=message, title="Переменная изменена")),
                daemon=True
            ).start()
        except Exception as e:
            logger.error(f"Failed to send Band notification: {e}")
    
    # Отправляем всем клиентам через WebSocket
    try:
        # Запускаем в отдельном потоке
        threading.Thread(
            target=lambda: asyncio.run(services.notify_clients({
                "type": "change_detected",
                "service": change["service"],
                "var_name": change["var_name"],
                "old_value": change["old_value"],
                "new_value": change["new_value"],
                "source": change["source"]
            })),
            daemon=True
        ).start()
    except Exception as e:
        logger.error(f"Failed to send WebSocket notification: {e}")
    
    # Логируем в БД (синхронно)
    def log_to_db():
        db = SessionLocal()
        try:
            from .models import ActionLog
            log = ActionLog(
                user="system",
                service=change["service"],
                var_name=change["var_name"],
                old_value=change["old_value"] or "",
                new_value=change["new_value"] or "",
                source="watcher"
            )
            db.add(log)
            db.commit()
            logger.info(f"Logged change to DB: {change['service']}.{change['var_name']}")
        except Exception as e:
            logger.error(f"Failed to log to DB: {e}")
        finally:
            db.close()
    
    # Запускаем логирование в отдельном потоке
    threading.Thread(target=log_to_db, daemon=True).start()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan контекст для старта/остановки"""
    global watcher, slack_notifier, band_notifier, _loop
    
    # Сохраняем ссылку на event loop
    _loop = asyncio.get_running_loop()
    
    # Инициализация нотифаеров
    if Config.SLACK_WEBHOOK_URL:
        slack_notifier = SlackNotifier(Config.SLACK_WEBHOOK_URL)
        logger.info("Slack notifier initialized")
    
    if Config.BAND_WEBHOOK_URL:
        band_notifier = BandNotifier(Config.BAND_WEBHOOK_URL)
        logger.info("Band notifier initialized")
    
        # Запускаем watcher (если не отключён)
        if not Config.DISABLE_WATCHER:
            db = SessionLocal()
            try:
                tracked_vars = get_tracked_vars_from_db(db)
                watcher = K8sWatcher(
                    namespace=Config.K8S_NAMESPACE,
                    on_change_callback=on_k8s_change,
                    tracked_vars_map=tracked_vars
                )
                watcher.start()
                logger.info(f"K8s watcher started, tracking {len(tracked_vars)} variables")
            finally:
                db.close()
        else:
            logger.info("K8s watcher disabled via DISABLE_WATCHER")
    
    yield
    
    # Остановка
    if watcher:
        watcher.stop()
        logger.info("K8s watcher stopped")

# FastAPI приложение
app = FastAPI(
    title="Mock Manager",
    description="Управление переменными в Kubernetes сервисах",
    version="1.0.0",
    debug=Config.DEBUG,
    lifespan=lifespan
)

@app.middleware("http")
async def log_requests(request, call_next):
    """Логирование всех HTTP запросов"""
    start_time = time.time()
    
    logger.info(f"➡️ {request.method} {request.url.path}")
    
    if request.method in ["POST", "PUT", "PATCH"]:
        try:
            body = await request.body()
            if body:
                logger.info(f"📦 Body: {body[:500]}")
        except:
            pass
    
    response = await call_next(request)
    
    duration = time.time() - start_time
    logger.info(f"⬅️ {request.method} {request.url.path} → {response.status_code} ({duration:.3f}s)")
    
    return response

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем роутеры
app.include_router(services.router)
app.include_router(groups.router)
app.include_router(variables.router)

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/api/info")
async def get_info():
    """Получить информацию о системе"""
    db = SessionLocal()
    try:
        from .models import Group
        tracked_count = db.query(TrackedVariable).count()
        groups_count = db.query(Group).count()
    finally:
        db.close()
    
    return {
        "namespace": Config.K8S_NAMESPACE,
        "tracked_variables": tracked_count,
        "groups": groups_count,
        "watcher_running": watcher is not None and watcher._thread and watcher._thread.is_alive() if watcher else False
    }