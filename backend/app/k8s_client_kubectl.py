import os
import threading
import subprocess
import json
import logging
from typing import Dict, List, Optional, Tuple
from types import SimpleNamespace

logger = logging.getLogger(__name__)


class K8sClient:
    def __init__(self, namespace: str, kubeconfig: Optional[str] = None):
        self.namespace = namespace
        self.kubeconfig = kubeconfig or os.getenv("KUBECONFIG", os.path.expanduser("~/.kube/config"))
        self._cache = {}
        self._cache_ttl = 30
        logger.info(f"Using kubectl with kubeconfig: {self.kubeconfig}")
    
    def _run_kubectl(self, args: List[str]) -> Tuple[bool, str]:
        """Синхронный запуск kubectl"""
        cmd = ["kubectl", f"--kubeconfig={self.kubeconfig}", "--namespace", self.namespace] + args
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.returncode == 0, result.stdout
        except Exception as e:
            logger.error(f"kubectl exception: {e}")
            return False, str(e)
    
    def _run_kubectl_async(self, args: List[str]):
        """Асинхронный запуск kubectl (не ждём результат)"""
        cmd = ["kubectl", f"--kubeconfig={self.kubeconfig}", "--namespace", self.namespace] + args
        logger.info(f"🚀 Асинхронный запуск: {' '.join(cmd)}")
        
        def _run():
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    logger.info(f"✅ Асинхронная команда выполнена успешно")
                else:
                    logger.error(f"❌ Асинхронная команда failed: {result.stderr[:200]}")
            except Exception as e:
                logger.error(f"❌ Асинхронная команда exception: {e}")
        
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
    
    def update_env_var_async(self, deployment_name: str, var_name: str, var_value: str) -> Tuple[bool, str]:
        """Асинхронное обновление переменной (не ждём kubectl)"""
        cmd = ["set", "env", "deployment", deployment_name, f"{var_name}={var_value}"]
        self._run_kubectl_async(cmd)
        
        # Очищаем кэш для этого deployment
        if deployment_name in self._cache:
            del self._cache[deployment_name]
        
        logger.info(f"✅ Команда отправлена: {deployment_name}.{var_name} = {var_value}")
        return True, ""  # Возвращаем успех сразу, не дожидаясь kubectl
    
    def get_deployment_env_vars(self, deployment_name: str) -> Dict[str, str]:
        """Получить env переменные (с кэшем)"""
        import time
        
        now = time.time()
        if deployment_name in self._cache and now - self._cache[deployment_name]['time'] < self._cache_ttl:
            return self._cache[deployment_name]['data']
        
        success, output = self._run_kubectl(["get", "deployment", deployment_name, "-o", "json"])
        
        result = {}
        if success and output:
            try:
                data = json.loads(output)
                containers = data.get('spec', {}).get('template', {}).get('spec', {}).get('containers', [])
                if containers:
                    env_vars = containers[0].get('env', [])
                    for env in env_vars:
                        if 'value' in env:
                            result[env['name']] = env['value']
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
        
        self._cache[deployment_name] = {'data': result, 'time': now}
        return result
    
    def get_deployments(self) -> List:
        success, output = self._run_kubectl(["get", "deployments", "-o", "json"])
        if success and output:
            try:
                data = json.loads(output)
                items = data.get('items', [])
                result = []
                for item in items:
                    name = item.get('metadata', {}).get('name')
                    if name:
                        result.append(SimpleNamespace(metadata=SimpleNamespace(name=name)))
                return result
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
        return []
    
    def get_all_deployments_data(self) -> Dict[str, Dict[str, str]]:
        import json
        import time
        
        start = time.time()
        success, output = self._run_kubectl([
            "get", "deployments",
            "-o", "jsonpath='{range .items[*]}{.metadata.name}{\"\\t\"}{.spec.template.spec.containers[0].env}{\"\\n\"}{end}'"
        ])
        
        logger.info(f"kubectl get all deployments took {time.time() - start:.2f}s")
        
        result = {}
        if success and output:
            for line in output.strip().split('\n'):
                line = line.strip("'")
                if '\t' in line:
                    parts = line.split('\t', 1)
                    if len(parts) == 2:
                        name, env_json = parts
                        env_vars = {}
                        if env_json and env_json != "[]" and env_json != "":
                            try:
                                env_json_fixed = env_json.replace("'", '"')
                                env_list = json.loads(env_json_fixed)
                                for env in env_list:
                                    if 'value' in env:
                                        env_vars[env['name']] = env['value']
                            except json.JSONDecodeError as e:
                                logger.warning(f"Failed to parse env for {name}: {e}")
                        result[name] = env_vars
        else:
            logger.error("Failed to get deployments data")
        
        logger.info(f"Parsed {len(result)} deployments")
        return result