import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Kubernetes
    K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "stage")
    K8S_KUBECONFIG = os.getenv("KUBECONFIG", os.path.expanduser("~/.kube/config"))
    
    # Database
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mock_manager.db")
    
    # Notifications
    SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
    BAND_WEBHOOK_URL = os.getenv("BAND_WEBHOOK_URL", "")
    
    # App
    DEBUG = os.getenv("DEBUG", "True").lower() == "true"
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    
    # Какие переменные отслеживать (если пусто - отслеживаем все)
    TRACKED_VARS = os.getenv("TRACKED_VARS", "").split(",") if os.getenv("TRACKED_VARS") else []
    
    # Server
    PORT = int(os.getenv("PORT", 8000))
    HOST = os.getenv("HOST", "0.0.0.0")
    
    # Test mode
    DISABLE_WATCHER = os.getenv("DISABLE_WATCHER", "").lower() in ("1", "true", "yes")