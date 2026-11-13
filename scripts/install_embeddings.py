from pathlib import Path
import os
ROOT=Path(__file__).resolve().parents[1]
os.environ["HF_HUB_DISABLE_TELEMETRY"]="1"
os.environ["HF_HOME"]=str(ROOT/".runtime"/"huggingface")
from huggingface_hub import snapshot_download
path=snapshot_download("BAAI/bge-small-zh-v1.5",local_dir=ROOT/"data"/"worker"/"embeddings"/"bge-small-zh-v1.5",
                       allow_patterns=["config.json","tokenizer.json","tokenizer_config.json","special_tokens_map.json","vocab.txt","model.safetensors","pytorch_model.bin"],max_workers=2)
print("Public embedding model installed:",path)
