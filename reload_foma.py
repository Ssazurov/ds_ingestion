import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from src.gar_client.client import GarClient
from src.gar_client.config import load_settings
from src.adapter.reload import reload_document

settings = load_settings()
source_dir = Path(settings.ds_search_root).resolve() / "data" / "raw" / "foma.ru"
state_path = Path(__file__).parent / "data" / "foma.ru.ingested.json"

with GarClient(settings) as client:
    dataset_id = client.ensure_dataset(settings.dataset_name)
    report = reload_document(client, dataset_id, source_dir, state_path, "1438163b9e439b03")
    print("OK", report)
