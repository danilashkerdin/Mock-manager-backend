import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import MagicMock, patch
from tests.MockK8sClient import MockK8sClient

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DISABLE_WATCHER"] = "true"

from app.main import app
from app.database import Base, get_db
from app.k8s_client_kubectl import K8sClient

# ========== Тестовая база данных ==========
# Используем SQLite в памяти для тестов
TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Переопределяем зависимость БД для тестов"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Подменяем зависимость в приложении
app.dependency_overrides[get_db] = override_get_db

# Создаём таблицы
Base.metadata.create_all(bind=engine)

# Патчим K8sClient в модулях приложения
@pytest.fixture(autouse=True)
def mock_k8s_client():
    """Автоматически подменяем K8sClient на мок для всех тестов"""
    mock_instance = MockK8sClient()
    with patch('app.api.services.k8s', mock_instance):
        with patch('app.api.groups.k8s', mock_instance):
            with patch('app.k8s_client_kubectl.K8sClient', lambda *a, **kw: mock_instance):
                yield


# ========== Тесты ==========

class TestHealth:
    """Тесты health check"""
    
    def test_health_endpoint(self):
        """GET /health - проверка здоровья"""
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}
    
    def test_info_endpoint(self):
        """GET /api/info - информация о системе"""
        client = TestClient(app)
        response = client.get("/api/info")
        assert response.status_code == 200
        data = response.json()
        assert "namespace" in data
        assert "tracked_variables" in data
        assert "groups" in data


class TestVariables:
    """Тесты для работы с переменными"""
    
    def setup_method(self):
        """Перед каждым тестом создаём новый клиент и чистим БД"""
        self.client = TestClient(app)
        # Очищаем БД через API
        vars_response = self.client.get("/api/variables/")
        for var in vars_response.json():
            self.client.delete(f"/api/variables/{var['id']}")
    
    def test_get_variables_empty(self):
        """GET /api/variables - сначала пусто"""
        response = self.client.get("/api/variables/")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_variable(self):
        """POST /api/variables - создать переменную"""
        data = {
            "name": "TEST_MOCK_1",
            "description": "Тестовая переменная",
            "services": ["payment-cards", "card-offers"]
        }
        response = self.client.post("/api/variables/", json=data)
        assert response.status_code == 200
        
        result = response.json()
        assert result["name"] == "TEST_MOCK_1"
        assert result["description"] == "Тестовая переменная"
        assert result["enabled"] == True
        assert "id" in result
    
    def test_create_variable_without_services(self):
        """POST /api/variables - создать переменную без сервисов (глобальную)"""
        data = {
            "name": "GLOBAL_MOCK",
            "description": "Глобальная переменная",
            "services": []
        }
        response = self.client.post("/api/variables/", json=data)
        assert response.status_code == 200
        
        result = response.json()
        assert result["name"] == "GLOBAL_MOCK"
        assert result["services"] == []
    
    def test_get_variables_list(self):
        """GET /api/variables - список переменных"""
        # Создаём переменную
        self.client.post("/api/variables/", json={
            "name": "LIST_MOCK",
            "description": "Для списка",
            "services": ["payment-cards"]
        })
        
        response = self.client.get("/api/variables/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["name"] == "LIST_MOCK"
    
    def test_create_duplicate_variable(self):
        """POST /api/variables - дубликат (должна быть ошибка)"""
        data = {
            "name": "DUPLICATE_VAR",
            "description": "Оригинал",
            "services": []
        }
        self.client.post("/api/variables/", json=data)
        
        # Пытаемся создать дубликат
        response = self.client.post("/api/variables/", json=data)
        assert response.status_code == 400
        assert "already tracked" in response.json()["detail"]
    
    def test_delete_variable(self):
        """DELETE /api/variables/{id} - удалить переменную"""
        # Создаём
        create_response = self.client.post("/api/variables/", json={
            "name": "TO_DELETE",
            "description": "Будет удалена",
            "services": []
        })
        var_id = create_response.json()["id"]
        
        # Удаляем
        response = self.client.delete(f"/api/variables/{var_id}")
        assert response.status_code == 200
        
        # Проверяем, что удалилась
        get_response = self.client.get("/api/variables/")
        for item in get_response.json():
            assert item["id"] != var_id
    
    def test_delete_nonexistent_variable(self):
        """DELETE /api/variables/{id} - удалить несуществующую"""
        response = self.client.delete("/api/variables/99999")
        assert response.status_code == 404


class TestServices:
    """Тесты для работы с сервисами"""
    
    def setup_method(self):
        self.client = TestClient(app)
    
    def test_get_services(self):
        """GET /api/services - список сервисов (моковые данные)"""
        response = self.client.get("/api/services/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Должны быть наши мок-сервисы
        names = [s["name"] for s in data]
        assert "payment-cards" in names
        assert "card-offers" in names
    
    def test_get_service_env_vars(self):
        """GET /api/services - проверка переменных в сервисе"""
        response = self.client.get("/api/services/")
        data = response.json()
        
        # Находим payment-cards
        payment_cards = next((s for s in data if s["name"] == "payment-cards"), None)
        assert payment_cards is not None
        assert "env_vars" in payment_cards
    
    def test_get_logs_empty(self):
        """GET /api/services/logs - логи (сначала пусто)"""
        response = self.client.get("/api/services/logs")
        assert response.status_code == 200
        assert response.json() == []
    
    def test_update_service_without_confirmation(self):
        """POST /api/services/update - без подтверждения (ошибка)"""
        # Сначала создаём переменную
        self.client.post("/api/variables/", json={
            "name": "MOCK_ENABLED",
            "description": "Тестовая",
            "services": ["payment-cards"]
        })
        
        data = {
            "service": "payment-cards",
            "var_name": "MOCK_ENABLED",
            "value": "true",
            "user": "tester",
            "confirmed": False
        }
        response = self.client.post("/api/services/update", json=data)
        assert response.status_code == 400
        assert "not confirmed" in response.json()["detail"]
    
    def test_update_service_with_confirmation(self):
        """POST /api/services/update - с подтверждением (должно работать)"""
        # Создаём переменную
        self.client.post("/api/variables/", json={
            "name": "MOCK_ENABLED",
            "description": "Тестовая",
            "services": ["payment-cards"]
        })
        
        data = {
            "service": "payment-cards",
            "var_name": "MOCK_ENABLED",
            "value": "true",
            "user": "tester",
            "confirmed": True
        }
        response = self.client.post("/api/services/update", json=data)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
    
    def test_update_service_with_untracked_variable(self):
        """POST /api/services/update - с неотслеживаемой переменной (ошибка)"""
        data = {
            "service": "payment-cards",
            "var_name": "VAR_THAT_DOES_NOT_EXIST",
            "value": "true",
            "user": "tester",
            "confirmed": True
        }
        response = self.client.post("/api/services/update", json=data)
        assert response.status_code == 400
        assert "not tracked" in response.json()["detail"]


class TestGroups:
    """Тесты для работы с группами"""
    
    def setup_method(self):
        self.client = TestClient(app)
        # Очищаем группы и переменные
        groups = self.client.get("/api/groups/").json()
        for g in groups:
            self.client.delete(f"/api/groups/{g['id']}")
        vars_list = self.client.get("/api/variables/").json()
        for v in vars_list:
            self.client.delete(f"/api/variables/{v['id']}")
    
    def test_get_groups_empty(self):
        """GET /api/groups - сначала пусто"""
        response = self.client.get("/api/groups/")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_groups_list(self):
        """GET /api/groups - список групп"""
        self.client.post("/api/variables/", json={
            "name": "LIST_GROUP_VAR",
            "description": "Для списка",
            "services": []
        })
        
        self.client.post("/api/groups/", json={
            "name": "Группа 1",
            "description": "Первая",
            "services": [{"service_name": "payment-cards", "var_name": "LIST_GROUP_VAR"}]
        })
        self.client.post("/api/groups/", json={
            "name": "Группа 2",
            "description": "Вторая",
            "services": [{"service_name": "card-offers", "var_name": "LIST_GROUP_VAR"}]
        })
        
        response = self.client.get("/api/groups/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 2
    
    def test_create_group(self):
        """POST /api/groups - создать группу (ID генерируется автоматически)"""
        # Создаём переменную
        self.client.post("/api/variables/", json={
            "name": "GROUP_TEST_VAR",
            "description": "Для группы",
            "services": []
        })
        
        data = {
            "name": "Тестовая группа",
            "description": "Группа для тестов",
            "services": [
                {"service_name": "payment-cards", "var_name": "GROUP_TEST_VAR"},
                {"service_name": "card-offers", "var_name": "GROUP_TEST_VAR"}
            ]
        }
        response = self.client.post("/api/groups/", json=data)
        assert response.status_code == 200
        
        result = response.json()
        assert "id" in result  # ID должен быть сгенерирован
        assert result["name"] == "Тестовая группа"
        assert len(result["services"]) == 2
    
    def test_create_group_with_different_variables(self):
        """POST /api/groups - группа с разными переменными для разных сервисов"""
        # Создаём переменные
        self.client.post("/api/variables/", json={
            "name": "MOCK_A",
            "description": "Мок А",
            "services": []
        })
        self.client.post("/api/variables/", json={
            "name": "MOCK_B",
            "description": "Мок Б",
            "services": []
        })
        
        data = {
            "id": "mixed-group",
            "name": "Смешанная группа",
            "description": "Разные переменные",
            "services": [
                {"service_name": "payment-cards", "var_name": "MOCK_A"},
                {"service_name": "card-offers", "var_name": "MOCK_B"}
            ]
        }
        response = self.client.post("/api/groups/", json=data)
        assert response.status_code == 200
        
        result = response.json()
        assert len(result["services"]) == 2
        assert result["services"][0]["var_name"] == "MOCK_A"
        assert result["services"][1]["var_name"] == "MOCK_B"
    
    def test_create_group_duplicate(self):
        """POST /api/groups - дубликат (ошибка)"""
        self.client.post("/api/variables/", json={
            "name": "DUPLICATE_GROUP_VAR",
            "description": "Для дубликата",
            "services": []
        })
        
        data = {
            "name": "Дубликат",
            "description": "Тест",
            "services": [
                {"service_name": "test", "var_name": "DUPLICATE_GROUP_VAR"}
            ]
        }
        # Создаём первую группу
        response1 = self.client.post("/api/groups/", json=data)
        assert response1.status_code == 200
        
        # Пытаемся создать группу с таким же именем (должно пройти, ID разные)
        response2 = self.client.post("/api/groups/", json=data)
        # Должно пройти успешно, так как ID генерируется автоматически
        assert response2.status_code == 200
    
    def test_update_group_without_confirmation(self):
        """POST /api/groups/update - без подтверждения (ошибка)"""
        # Создаём группу
        self.client.post("/api/variables/", json={
            "name": "UPDATE_GROUP_VAR",
            "description": "Для обновления",
            "services": []
        })
        
        self.client.post("/api/groups/", json={
            "id": "update-group",
            "name": "Update Group",
            "description": "Test",
            "services": [
                {"service_name": "payment-cards", "var_name": "UPDATE_GROUP_VAR"}
            ]
        })
        
        data = {
            "group_id": "update-group",
            "enabled": True,
            "user": "tester",
            "confirmed": False
        }
        response = self.client.post("/api/groups/update", json=data)
        assert response.status_code == 400
        assert "not confirmed" in response.json()["detail"]
    
    def test_update_group_with_confirmation(self):
        """POST /api/groups/update - с подтверждением"""
        # Создаём переменную
        self.client.post("/api/variables/", json={
            "name": "GROUP_MOCK",
            "description": "Для группы",
            "services": ["payment-cards", "card-offers"]
        })
        
        # Создаём группу БЕЗ указания id (он генерируется автоматически)
        create_response = self.client.post("/api/groups/", json={
            "name": "Enabled Group",
            "description": "Test",
            "services": [
                {"service_name": "payment-cards", "var_name": "GROUP_MOCK"},
                {"service_name": "card-offers", "var_name": "GROUP_MOCK"}
            ]
        })
        assert create_response.status_code == 200
        group_id = create_response.json()["id"]
        
        data = {
            "group_id": group_id,
            "enabled": True,
            "user": "tester",
            "confirmed": True
        }
        response = self.client.post("/api/groups/update", json=data)
        assert response.status_code == 200
        assert "updated_services" in response.json()

    def test_delete_group(self):
        """DELETE /api/groups/{id} - удалить группу"""
        self.client.post("/api/variables/", json={
            "name": "DELETE_GROUP_VAR",
            "description": "Для удаления",
            "services": []
        })
        
        # Создаём группу
        create_response = self.client.post("/api/groups/", json={
            "name": "На удаление",
            "description": "Будет удалена",
            "services": [
                {"service_name": "test", "var_name": "DELETE_GROUP_VAR"}
            ]
        })
        group_id = create_response.json()["id"]
        
        # Удаляем
        response = self.client.delete(f"/api/groups/{group_id}")
        assert response.status_code == 200
    
    def test_delete_nonexistent_group(self):
        """DELETE /api/groups/{id} - удалить несуществующую группу"""
        response = self.client.delete("/api/groups/nonexistent-group-12345")
        assert response.status_code == 404


class TestLogs:
    """Тесты для логов"""
    
    def setup_method(self):
        self.client = TestClient(app)
    
    def test_get_logs(self):
        """GET /api/services/logs - получить логи"""
        response = self.client.get("/api/services/logs")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
    
    def test_get_logs_with_limit(self):
        """GET /api/services/logs?limit=5 - с лимитом"""
        response = self.client.get("/api/services/logs?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 5
    
    def test_get_logs_for_service(self):
        """GET /api/services/logs/{service} - логи конкретного сервиса"""
        response = self.client.get("/api/services/logs/payment-cards")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

class TestGlobalVariable:
    """Тесты для глобальной переменной"""
    
    def setup_method(self):
        self.client = TestClient(app)
        # Очищаем переменные перед тестом
        vars_list = self.client.get("/api/variables/").json()
        for v in vars_list:
            self.client.delete(f"/api/variables/{v['id']}")
    
    def test_global_variable_creation(self):
        """Создание глобальной переменной"""
        response = self.client.post("/api/variables/", json={
            "name": "GLOBAL_DEBUG",
            "description": "Глобальная переменная",
            "services": []
        })
        assert response.status_code == 200
        assert response.json()["services"] == []

    def test_global_variable_appears_in_multiple_services(self):
        """Глобальная переменная может быть добавлена в несколько сервисов"""
        # Создаём глобальную переменную
        self.client.post("/api/variables/", json={
            "name": "GLOBAL_DEBUG",
            "description": "Глобальная переменная",
            "services": []
        })
        
        # Добавляем в payment-cards
        self.client.post("/api/services/update", json={
            "service": "payment-cards",
            "var_name": "GLOBAL_DEBUG",
            "value": "true",
            "user": "tester",
            "confirmed": True
        })
        
        # Добавляем в card-offers
        self.client.post("/api/services/update", json={
            "service": "card-offers",
            "var_name": "GLOBAL_DEBUG",
            "value": "enabled",
            "user": "tester",
            "confirmed": True
        })
        
        # Проверяем оба сервиса
        services_response = self.client.get("/api/services/")
        services = services_response.json()
        
        payment_cards = next(s for s in services if s["name"] == "payment-cards")
        assert payment_cards["tracked_vars"].get("GLOBAL_DEBUG") == "true"
        
        card_offers = next(s for s in services if s["name"] == "card-offers")
        assert card_offers["tracked_vars"].get("GLOBAL_DEBUG") == "enabled"


class TestFullScenario:
    """Полный сценарий использования"""
    
    def setup_method(self):
        self.client = TestClient(app)
        
    def test_full_workflow(self):
        """Полный цикл: создать переменную -> создать группу -> обновить -> удалить"""
        
        # 1. Создаём переменную
        var_response = self.client.post("/api/variables/", json={
            "name": "WORKFLOW_MOCK",
            "description": "Для полного сценария",
            "services": ["payment-cards", "card-offers", "compass-proxy"]
        })
        assert var_response.status_code == 200
        var_id = var_response.json()["id"]
        
        # 2. Создаём группу (без ID)
        group_response = self.client.post("/api/groups/", json={
            "name": "Сценарий группа",
            "description": "Группа для теста сценария",
            "services": [
                {"service_name": "payment-cards", "var_name": "WORKFLOW_MOCK"},
                {"service_name": "card-offers", "var_name": "WORKFLOW_MOCK"}
            ]
        })
        assert group_response.status_code == 200
        group_id = group_response.json()["id"]
        
        # 3. Проверяем группу
        get_groups = self.client.get("/api/groups/")
        group_found = False
        for g in get_groups.json():
            if g["id"] == group_id:
                group_found = True
                break
        assert group_found == True
        
        # 4. Обновляем группу
        update_response = self.client.post("/api/groups/update", json={
            "group_id": group_id,
            "enabled": True,
            "user": "tester",
            "confirmed": True
        })
        assert update_response.status_code == 200
        
        # 5. Удаляем группу
        delete_group = self.client.delete(f"/api/groups/{group_id}")
        assert delete_group.status_code == 200
        
        # 6. Удаляем переменную
        delete_var = self.client.delete(f"/api/variables/{var_id}")
        assert delete_var.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])