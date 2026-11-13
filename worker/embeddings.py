"""Offline BGE Chinese embeddings using public weights. No external requests at inference."""
import threading
from pathlib import Path
from worker.service import ROOT

MODEL_PATH=ROOT/"embeddings"/"bge-small-zh-v1.5"
LOCK=threading.Lock()
_model=None
_tokenizer=None

def encode(texts:list[str], query:bool=False):
    global _model,_tokenizer
    if not MODEL_PATH.exists():raise ValueError("本地 Embedding 模型未安装")
    if not texts or len(texts)>32 or any(not isinstance(t,str) or not t.strip() or len(t)>8000 for t in texts):
        raise ValueError("Embedding 输入须为 1–32 段非空文本，每段最多 8000 字符")
    with LOCK:
        import torch
        from transformers import AutoTokenizer,AutoModel
        if _model is None:
            _tokenizer=AutoTokenizer.from_pretrained(MODEL_PATH,local_files_only=True)
            _model=AutoModel.from_pretrained(MODEL_PATH,local_files_only=True).eval()
        inputs=["为这个句子生成表示以用于检索相关文章："+t if query else t for t in texts]
        tokens=_tokenizer(inputs,padding=True,truncation=True,max_length=512,return_tensors="pt")
        with torch.inference_mode():
            vectors=torch.nn.functional.normalize(_model(**tokens).last_hidden_state[:,0],p=2,dim=1)
        return vectors.cpu().tolist()
