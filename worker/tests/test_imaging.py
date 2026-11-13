import json
import os
import tempfile
import time
from pathlib import Path

os.environ["MEDAGENT_DATA_DIR"] = tempfile.mkdtemp(prefix="medagent-tests-")
import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient
from worker import service
from worker.app import app

def test_demo_result_geometry_and_idempotency():
    info=service.create_demo()
    assert info["synthetic"] is True
    job=service.submit_segmentation(info["fileId"],["liver","spleen"],demo=True,request_key="test-once")
    for _ in range(100):
        state=service.get_job(job["id"])
        if state["status"] in ("SUCCEEDED","FAILED"): break
        time.sleep(.05)
    assert state["status"]=="SUCCEEDED",state
    r=state["result"]
    _,masks=service.demo_geometry()
    assert r["statistics"][0]["volumeMl"]==round(masks["liver"].sum()*12/1000,3)
    source=nib.load(service.input_path(info["fileId"]))
    output=nib.load(service.ROOT/"jobs"/job["id"]/"liver.nii.gz")
    assert output.shape==source.shape
    np.testing.assert_allclose(output.affine,source.affine)
    assert service.submit_segmentation(info["fileId"],["liver","spleen"],demo=True,request_key="test-once")["id"]==job["id"]
    with pytest.raises(ValueError,match="幂等"):
        service.submit_segmentation(info["fileId"],["liver"],demo=True,request_key="test-once")

def test_mode_and_path_boundaries():
    with pytest.raises(ValueError): service.input_path("../../private")
    info=service.create_demo()
    with pytest.raises(ValueError,match="合成"):
        service.submit_segmentation(info["fileId"],["liver"],demo=False)
    with pytest.raises(ValueError,match="只支持"):
        service.submit_segmentation(info["fileId"],["unknown"],demo=True)

def test_cancel_queued_job_never_starts(monkeypatch):
    monkeypatch.setattr(service.POOL,"submit",lambda *a,**kw:None)
    info=service.create_demo()
    job=service.submit_segmentation(info["fileId"],["liver"],demo=True)
    assert service.cancel_job(job["id"])["status"]=="CANCELLED"
    service.run_job(job["id"])
    assert service.get_job(job["id"])["status"]=="CANCELLED"
    assert "result" not in service.get_job(job["id"])

def test_unknown_units_and_4d_rejected(tmp_path):
    path=tmp_path/"bad.nii.gz"
    nib.save(nib.Nifti1Image(np.zeros((4,4,4)),np.eye(4)),path)
    with pytest.raises(ValueError,match="mm"): service.read_image(path)
    image=nib.Nifti1Image(np.zeros((4,4,4,2)),np.eye(4));image.header.set_xyzt_units("mm");nib.save(image,path)
    with pytest.raises(ValueError,match="三维"): service.read_image(path)

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as instance:
        yield instance

def test_uncompressed_nii_upload(tmp_path,client):
    image=nib.Nifti1Image(np.ones((4,5,6),dtype=np.float32),np.diag([2.,2.,3.,1.]))
    image.header.set_xyzt_units("mm")
    path=tmp_path/"public-synthetic.nii";nib.save(image,path)
    response=client.post("/files",files={"file":("public-synthetic.nii",path.read_bytes())})
    assert response.status_code==200,response.text
    assert response.json()["shape"]==[4,5,6]
    assert response.json()["synthetic"] is False
    uploaded=nib.load(service.input_path(response.json()["fileId"]))
    np.testing.assert_allclose(uploaded.get_fdata(),image.get_fdata())

def test_mcp_protocol_and_upload_validation(client):
    headers={"Accept":"application/json, text/event-stream"}
    response=client.post("/mcp",headers=headers,json={"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}})
    assert response.status_code==200,response.text
    response=client.post("/mcp",headers=headers,json={"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}})
    assert "submit_segmentation" in [t["name"] for t in response.json()["result"]["tools"]]
    info=client.post("/files/demo").json()
    response=client.post("/mcp",headers=headers,json={"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"inspect_image","arguments":{"file_id":info["fileId"]}}})
    assert json.loads(response.json()["result"]["content"][0]["text"])["synthetic"]
    assert client.post("/files",files={"file":("bad.nii.gz",b"not-nifti")}).status_code==400
    assert client.post("/files",files={"file":("file.txt",b"text")}).status_code==400
    assert client.get("/artifacts/"+info["fileId"]+"/private.json").status_code in (400,404)
