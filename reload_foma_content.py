from pathlib import Path
from src.gar_client.client import GarClient
from src.gar_client.config import load_settings

settings = load_settings()
content_path = Path(settings.ds_search_root).resolve() / "data" / "raw" / "foma.ru" / "1438163b9e439b03.md"
print("content_path exists:", content_path.is_file())

with GarClient(settings) as client:
    client.update_document_content("ad1fb0e2-3c2b-430e-8a6c-c3c51e35d3d4", content_path)
    print("content updated OK")
