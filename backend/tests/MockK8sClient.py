import json
import os
from types import SimpleNamespace


def _load_mock_data() -> dict[str, dict[str, str]]:
    base = os.path.dirname(__file__)
    candidates = [
        os.environ.get("MOCK_DATA_PATH"),
        os.path.join(base, "mock_data.json"),
        os.path.join(base, "mock_data.example.json"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            return {k: v for k, v in data.items() if not k.startswith("_")}
    return {}  # fallback — пустой список сервисов


class MockK8sClient:
    """Mock for K8sClient, simulates real cluster behavior.
    Service data is loaded from mock_data.json by default,
    override with MOCK_DATA_PATH env var."""

    def __init__(self, namespace=None, kubeconfig=None):
        self.namespace = namespace or "test-namespace"
        self._env_vars = _load_mock_data()

    def get_deployments(self):
        return [
            SimpleNamespace(metadata=SimpleNamespace(name=name))
            for name in self._env_vars
        ]

    def get_deployment_env_vars(self, deployment_name: str) -> dict[str, str]:
        return self._env_vars.get(deployment_name, {}).copy()

    def get_all_deployments_data(self) -> dict[str, dict[str, str]]:
        return {name: vars.copy() for name, vars in self._env_vars.items()}

    def update_env_var(self, deployment_name: str, var_name: str, var_value: str):
        if deployment_name not in self._env_vars:
            self._env_vars[deployment_name] = {}
        old_value = self._env_vars[deployment_name].get(var_name, "")
        if var_value == "" or var_value is None:
            self._env_vars[deployment_name].pop(var_name, None)
        else:
            self._env_vars[deployment_name][var_name] = var_value
        return True, old_value

    def update_env_var_async(self, deployment_name: str, var_name: str, var_value: str):
        return self.update_env_var(deployment_name, var_name, var_value)
