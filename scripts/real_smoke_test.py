"""Optional integration check using the official public, downsampled CT test fixture."""
import hashlib
import json
import time
from pathlib import Path
import nibabel as nib
import requests

ROOT=Path(__file__).resolve().parents[1]
SAMPLES=ROOT/"data"/"samples"
SAMPLES.mkdir(parents=True,exist_ok=True)
URL="https://raw.githubusercontent.com/wasserth/TotalSegmentator/master/tests/reference_files/example_ct_sm.nii.gz"
original=SAMPLES/"example_ct_sm.nii.gz"
if not original.exists():
    response=requests.get(URL,timeout=90);response.raise_for_status();original.write_bytes(response.content)
image=nib.load(original)
original_units=image.header.get_xyzt_units()[0]
# The official TotalSegmentator CT fixture has unspecified NIfTI units. Its pipeline
# interprets voxel spacing as millimeters. Explicitly record that assumption; preserve original.
image.header.set_xyzt_units("mm")
prepared=SAMPLES/"example_ct_sm_mm.nii.gz"
nib.save(image,prepared)
provenance={"source":URL,"originalSha256":hashlib.sha256(original.read_bytes()).hexdigest(),"originalUnits":original_units,
            "preparedUnits":"mm","note":"Official CT test fixture; explicit millimeter assumption, no pixel/affine changes. For software integration validation only, not accuracy evaluation."}
(SAMPLES/"source.json").write_text(json.dumps(provenance,indent=2),encoding="utf-8")
base="http://127.0.0.1:8080/api"
with prepared.open("rb") as f:
    r=requests.post(base+"/files",files={"file":(prepared.name,f,"application/octet-stream")},timeout=90)
r.raise_for_status();file=r.json()
r=requests.post(base+"/tasks",json={"kind":"analysis","prompt":"分割肝脏、脾脏和双肾，计算体积，并检索方法说明。","fileId":file["fileId"],"demo":False,"fast":True,"localOnly":True,"organs":["liver","spleen","kidney_left","kidney_right"]},timeout=90)
r.raise_for_status();task=r.json();print("task="+task["id"],flush=True)
for i in range(900):
    r=requests.get(base+"/tasks/"+task["id"],timeout=90);r.raise_for_status();task=r.json()
    if task["status"] in ("SUCCEEDED","FAILED","CANCELLED"):break
    if i%15==0:print(task["status"],flush=True)
    time.sleep(2)
(ROOT/".runtime"/"real-inference-result.json").write_text(json.dumps(task,ensure_ascii=False,indent=2),encoding="utf-8")
assert task["status"]=="SUCCEEDED",task.get("error",task)
assert task["result"]["demo"] is False
assert any(row["voxelCount"]>0 for row in task["result"]["statistics"])
print(json.dumps({"passed":True,"task":task["id"],"model":task["result"]["model"],"seconds":task["result"]["elapsedSeconds"],"statistics":task["result"]["statistics"]},ensure_ascii=False),flush=True)
