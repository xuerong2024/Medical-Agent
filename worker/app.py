import importlib.util
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from mcp.server.fastmcp import FastMCP
from worker import service
from pydantic import BaseModel

class EmbeddingInput(BaseModel):
    model:str="BAAI/bge-small-zh-v1.5"
    input:str|list[str]
    input_type:str="document"

mcp = FastMCP("Medical Agent Imaging", stateless_http=True, json_response=True)
mcp.tool()(service.inspect_image)
mcp.tool()(service.submit_segmentation)
mcp.tool()(service.get_job)
mcp.tool()(service.cancel_job)

@asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():
        yield

app = FastAPI(title="Medical Agent Local Imaging", lifespan=lifespan)

@app.exception_handler(ValueError)
async def invalid_request(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=400, content={"detail": str(exc)})

@app.get("/health")
def health():
    return {"status": "ok", "modelInstalled": importlib.util.find_spec("totalsegmentator") is not None,
            "organs": service.ORGANS, "mcp": "/mcp", "device": __import__("os").environ.get("TOTALSEG_DEVICE", "cpu")}

@app.post("/files/demo")
def demo():
    return service.create_demo()

@app.post("/v1/embeddings")
def embeddings(request:EmbeddingInput):
    from worker.embeddings import encode
    if request.model!="BAAI/bge-small-zh-v1.5":raise ValueError("未知 Embedding 模型")
    values=encode([request.input] if isinstance(request.input,str) else request.input,request.input_type=="query")
    return {"object":"list","model":request.model,"data":[{"object":"embedding","index":i,"embedding":v} for i,v in enumerate(values)]}

@app.post("/files")
async def upload(file: UploadFile):
    if not file.filename or not file.filename.lower().endswith((".nii.gz", ".nii")):
        raise ValueError("只接受 .nii 或 .nii.gz 文件")
    file_id = str(uuid.uuid4())
    path = service.ROOT / "uploads" / (file_id + ".nii.gz")
    uploaded = path if file.filename.lower().endswith(".nii.gz") else path.with_suffix("")
    total = 0
    try:
        with uploaded.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > 256 * 1024 * 1024:
                    raise ValueError("文件不能超过 256 MiB")
                output.write(chunk)
        image=service.read_image(uploaded)
        if uploaded!=path:
            import nibabel as nib
            nib.save(image,path)
            uploaded.unlink()
        path.with_suffix(".json").write_text(json.dumps({"synthetic": False}), encoding="utf-8")
        return service.inspect_image(file_id)
    except Exception as exc:
        path.unlink(missing_ok=True)  # Only the newly created UUID file inside project uploads.
        if uploaded!=path:uploaded.unlink(missing_ok=True)
        raise ValueError("影像上传失败：" + str(exc)[:200])

@app.get("/artifacts/{job_id}/{name}")
def artifact(job_id: str, name: str):
    job = service.get_job(job_id)
    result = job.get("result", {})
    allowed = result.get("previews", []) + result.get("masks", []) + (["result.json"] if result else [])
    if job["status"] != "SUCCEEDED" or name not in allowed or Path(name).name != name:
        raise HTTPException(404, "产物不存在")
    return FileResponse(service.ROOT / "jobs" / job_id / name)

app.mount("/", mcp.streamable_http_app())
