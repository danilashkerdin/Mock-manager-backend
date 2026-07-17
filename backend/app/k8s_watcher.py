import threading
import logging
from typing import Callable, Dict, List, Optional, Set
from kubernetes import watch, config
from kubernetes.client import AppsV1Api
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

class K8sWatcher:
    def __init__(
        self, 
        namespace: str, 
        on_change_callback: Callable,
        tracked_vars_map: Optional[Dict[str, Set[str]]] = None
    ):
        """
        tracked_vars_map: словарь, где ключ - имя переменной, значение - множество сервисов
        Пример: {
            "FEIGN_EXTERNAL_API": {"service-a", "service-b"},
            "MOCK_ENABLED": {"service-c"}
        }
        Если сервисов нет в множестве - переменная НЕ отслеживается в этом сервисе
        """
        self.namespace = namespace
        self.on_change = on_change_callback
        self.tracked_vars_map = tracked_vars_map or {}
        self._stop_event = threading.Event()
        self._thread = None
        self._current_state: Dict[str, Dict[str, str]] = {}
        self._error_count = 0
    
    def update_tracked_vars(self, tracked_vars_map: Dict[str, Set[str]]):
        """Обновить список отслеживаемых переменных"""
        self.tracked_vars_map = tracked_vars_map
        logger.info(f"Tracked vars map updated: {tracked_vars_map}")
    
    def start(self):
        """Запустить watcher в отдельном потоке"""
        if self._thread and self._thread.is_alive():
            logger.warning("Watcher already running")
            return
        
        self._stop_event.clear()
        self._error_count = 0
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        logger.info(f"K8s watcher started, tracking {len(self.tracked_vars_map)} variables")
    
    def stop(self):
        """Остановить watcher"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("K8s watcher stopped")
    
    def _should_track(self, service_name: str, var_name: str) -> bool:
        """Проверить, нужно ли отслеживать переменную в этом сервисе"""
        if var_name not in self.tracked_vars_map:
            return False
        allowed_services = self.tracked_vars_map[var_name]
        if not allowed_services:
            return True
        return service_name in allowed_services
    
    def _get_env_vars_from_deployment(self, deployment) -> Dict[str, str]:
        """Извлечь env переменные из deployment объекта"""
        env_vars = {}
        try:
            if deployment.spec.template.spec.containers:
                container = deployment.spec.template.spec.containers[0]
                if container.env:
                    for env in container.env:
                        if env.value is not None:
                            env_vars[env.name] = env.value
                        else:
                            env_vars[env.name] = ""
            logger.debug(f"Extracted {len(env_vars)} env vars from {deployment.metadata.name}")
        except Exception as e:
            logger.error(f"Error extracting env vars: {e}")
        return env_vars
    
    def _watch(self):
        """Основной цикл отслеживания"""
        try:
            config.load_kube_config()
            v1 = AppsV1Api()
            watcher = watch.Watch()
            
            initial_sync_done = False
            sync_count = 0
            total_deployments = 0
            
            while not self._stop_event.is_set():
                try:
                    for event in watcher.stream(
                        v1.list_namespaced_deployment,
                        namespace=self.namespace,
                        timeout_seconds=60,
                        _request_timeout=60
                    ):
                        if self._stop_event.is_set():
                            watcher.stop()
                            break
                        
                        deployment = event['object']
                        deployment_name = deployment.metadata.name
                        env_vars = self._get_env_vars_from_deployment(deployment)
                        
                        # Фильтруем только отслеживаемые
                        tracked_current = {}
                        for var_name, var_value in env_vars.items():
                            if self._should_track(deployment_name, var_name):
                                tracked_current[var_name] = var_value
                        
                        old_state = self._current_state.get(deployment_name, {})
                        
                        # Проверяем изменения
                        for var_name, new_value in tracked_current.items():
                            old_value = old_state.get(var_name)
                            if old_value != new_value:
                                if not initial_sync_done:
                                    logger.debug(f"Initial sync: {deployment_name}.{var_name} = {new_value}")
                                    continue
                                
                                logger.info(f"Change detected: {deployment_name}.{var_name} = {new_value} (was {old_value})")
                                self.on_change({
                                    "service": deployment_name,
                                    "var_name": var_name,
                                    "old_value": old_value,
                                    "new_value": new_value,
                                    "source": "k8s_watcher"
                                })
                        
                        self._current_state[deployment_name] = tracked_current
                        sync_count += 1
                        
                        if not initial_sync_done and total_deployments == 0:
                            total_deployments = len(self._current_state)
                        
                        if not initial_sync_done and sync_count >= total_deployments and total_deployments > 0:
                            initial_sync_done = True
                            logger.info(f"Initial sync completed for {total_deployments} deployments, now tracking changes")
                        
                except ApiException as e:
                    logger.error(f"Watcher API error: {e}")
                    if e.status == 403:
                        logger.error("Authentication error - check your kubeconfig")
                        break
                except Exception as e:
                    logger.error(f"Watcher error: {e}")
                
                if not self._stop_event.is_set():
                    logger.info("Reconnecting watcher...")
                    watcher = watch.Watch()
                    threading.Event().wait(5)
                    
        except Exception as e:
            logger.error(f"Fatal watcher error: {e}")