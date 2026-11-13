"""Local imaging boundary. Never reads arbitrary caller-provided filesystem paths."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import nibabel as nib
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(os.environ.get("MEDAGENT_DATA_DIR", str(Path(__file__).resolve().parents[1] / "data" / "worker"))).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
for sub in ("uploads", "jobs", "models"):
    (ROOT / sub).mkdir(exist_ok=True)
ORGANS = {"liver": "肝脏", "spleen": "脾脏", "kidney_left": "左肾", "kidney_right": "右肾"}
COLORS = {"liver": (67, 207, 177), "spleen": (255, 187, 96), "kidney_left": (127, 164, 255), "kidney_right": (231, 131, 198)}
POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="imaging")
LOCK = threading.RLock()
JOBS: dict[str, dict] = {}
PROCESSES: dict[str, subprocess.Popen] = {}
for saved in (ROOT / "jobs").glob("*/job.json"):
    try:
        job = json.loads(saved.read_text(encoding="utf-8"))
        if job["status"] in ("QUEUED", "RUNNING"):
            job.update(status="FAILED", error="服务重启，中断的任务需要重新提交")
            saved.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        JOBS[job["id"]] = job
    except (ValueError, KeyError, OSError):
        pass


def identifier(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("无效的资源 ID")


def input_path(file_id: str) -> Path:
    path = ROOT / "uploads" / (identifier(file_id) + ".nii.gz")
    if not path.is_file():
        raise ValueError("影像不存在，请重新上传")
    return path


def read_image(path: Path):
    image = nib.load(str(path))
    if len(image.shape) != 3 or min(image.shape) < 2 or np.prod(image.shape, dtype=np.int64) > 128_000_000:
        raise ValueError("只接受三维 NIfTI，体素数须不超过 1.28 亿")
    if not np.isfinite(image.affine).all() or abs(np.linalg.det(image.affine[:3, :3])) < 1e-9:
        raise ValueError("影像空间变换无效")
    if image.header.get_xyzt_units()[0] != "mm":
        raise ValueError("第一版要求空间单位为 mm，请先规范化影像单位")
    if image.get_data_dtype().kind not in "iuf":
        raise ValueError("不支持复数或非数值影像")
    return image


def inspect_image(file_id: str) -> dict:
    path = input_path(file_id)
    image = read_image(path)
    meta_path = path.with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return {"fileId": file_id, "shape": list(image.shape), "spacingMm": [float(v) for v in image.header.get_zooms()[:3]],
            "orientation": list(nib.aff2axcodes(image.affine)), "modality": "CT (用户确认)", "synthetic": meta.get("synthetic", False),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "sizeBytes": path.stat().st_size}


def demo_geometry():
    grid = np.indices((96, 96, 64), dtype=np.float32)
    x, y, z = grid
    body = ((x - 48) / 39)**2 + ((y - 47) / 31)**2 < 1
    image = np.where(body, 25., -1000.).astype(np.float32)
    shapes = [("liver", (29, 46, 35), (17, 17, 17)), ("spleen", (70, 48, 37), (9, 14, 13)),
              ("kidney_left", (65, 35, 25), (7, 9, 11)), ("kidney_right", (32, 32, 24), (7, 9, 11))]
    masks = {}
    for index, (name, center, radius) in enumerate(shapes):
        mask = sum(((grid[i] - center[i]) / radius[i])**2 for i in range(3)) <= 1
        masks[name] = mask
        image[mask] = 65 + index * 15
    image += np.random.default_rng(7).normal(0, 5, image.shape).astype(np.float32)
    return image, masks


def create_demo() -> dict:
    file_id = str(uuid.uuid4())
    data, _ = demo_geometry()
    image = nib.Nifti1Image(data, np.diag([2., 2., 3., 1.]))
    image.header.set_xyzt_units("mm")
    path = ROOT / "uploads" / (file_id + ".nii.gz")
    nib.save(image, path)
    path.with_suffix(".json").write_text(json.dumps({"synthetic": True}), encoding="utf-8")
    return inspect_image(file_id)


def save_job(job: dict):
    directory = ROOT / "jobs" / job["id"]
    directory.mkdir(exist_ok=True)
    target = directory / "job.json"
    tmp = directory / "job.tmp"
    tmp.write_text(json.dumps(job, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    tmp.replace(target)


def get_job(job_id: str) -> dict:
    with LOCK:
        if identifier(job_id) not in JOBS:
            raise ValueError("任务不存在")
        return json.loads(json.dumps(JOBS[job_id]))


def submit_segmentation(file_id: str, organs: list[str], fast: bool = True, demo: bool = False, request_key: str = "") -> dict:
    metadata = inspect_image(file_id)
    organs = list(dict.fromkeys(organs))
    if not organs or any(o not in ORGANS for o in organs):
        raise ValueError("只支持 liver、spleen、kidney_left、kidney_right")
    if demo != metadata["synthetic"]:
        raise ValueError("合成演示只能处理系统生成的影像；真实影像必须使用 TotalSegmentator")
    if not demo and importlib.util.find_spec("totalsegmentator") is None:
        raise ValueError("尚未安装真实模型依赖，请运行 scripts/install-model.ps1")
    fingerprint = json.dumps([file_id, organs, fast, demo])
    with LOCK:
        for existing in JOBS.values():
            if request_key and existing.get("requestKey") == request_key:
                if existing["fingerprint"] != fingerprint:
                    raise ValueError("同一幂等键不能用于不同参数")
                return get_job(existing["id"])
        if sum(j["status"] in ("QUEUED", "RUNNING") for j in JOBS.values()) >= 4:
            raise ValueError("推理队列已满，请稍后提交")
        job = {"id": str(uuid.uuid4()), "fileId": file_id, "organs": organs, "fast": fast, "demo": demo,
               "requestKey": request_key, "fingerprint": fingerprint, "status": "QUEUED", "createdAt": time.time(),
               "model": "synthetic-geometry-v1 (非 AI 推理)" if demo else "TotalSegmentator / total", "inputSha256": metadata["sha256"]}
        JOBS[job["id"]] = job
        save_job(job)
        POOL.submit(run_job, job["id"])
        return get_job(job["id"])


def cancel_job(job_id: str) -> dict:
    with LOCK:
        job = JOBS[identifier(job_id)]
        if job["status"] in ("QUEUED", "RUNNING"):
            job.update(status="CANCELLED", error="用户取消任务")
            process = PROCESSES.get(job_id)
            if process and process.poll() is None:
                import psutil
                try:
                    parent = psutil.Process(process.pid)
                    for child in parent.children(recursive=True):
                        child.kill()
                    parent.kill()
                except psutil.NoSuchProcess:
                    pass
            save_job(job)
        return get_job(job_id)


def summarize(image, masks: dict, directory: Path) -> tuple[list, list]:
    data = image.get_fdata(dtype=np.float32)
    if not np.isfinite(data).all():
        raise ValueError("影像包含非有限数值")
    voxel_mm3 = abs(float(np.linalg.det(image.affine[:3, :3])))
    stats = []
    for name, mask in masks.items():
        count = int(mask.sum())
        border = any(np.any(np.take(mask, [0, -1], axis=axis)) for axis in range(3))
        stats.append({"organ": name, "label": ORGANS[name], "voxelCount": count,
                      "volumeMl": round(count * voxel_mm3 / 1000, 3),
                      "meanIntensity": round(float(data[mask].mean()), 3) if count else None,
                      "touchesBorder": border, "empty": count == 0})
    canonical = nib.as_closest_canonical(image)
    canonical_data = canonical.get_fdata(dtype=np.float32)
    cmasks = {n: nib.as_closest_canonical(nib.Nifti1Image(m.astype(np.uint8), image.affine)).get_fdata() > 0 for n, m in masks.items()}
    union = np.logical_or.reduce(list(cmasks.values()))
    center = np.mean(np.argwhere(union), axis=0).astype(int) if union.any() else np.array(canonical.shape) // 2
    artifacts = []
    for axis, label in [(2, "axial"), (1, "coronal"), (0, "sagittal")]:
        gray = np.rot90(np.take(canonical_data, center[axis], axis=axis))
        gray = (np.clip((gray + 160) / 400, 0, 1) * 255).astype(np.uint8)
        rgb = np.stack([gray] * 3, axis=-1)
        for name, mask in cmasks.items():
            plane = np.rot90(np.take(mask, center[axis], axis=axis))
            rgb[plane] = (rgb[plane] * .45 + np.array(COLORS[name]) * .55).astype(np.uint8)
        axes = [a for a in range(3) if a != axis]
        spacing = canonical.header.get_zooms()
        aspect = (canonical.shape[axes[1]] * spacing[axes[1]]) / (canonical.shape[axes[0]] * spacing[axes[0]])
        picture = Image.fromarray(rgb).resize((480, max(100, int(480 * aspect))), Image.Resampling.NEAREST)
        ImageDraw.Draw(picture).text((12, 12), f"{label.upper()} / RAS+ / research preview", fill="white")
        name = label + ".png"
        picture.save(directory / name)
        artifacts.append(name)
    return stats, artifacts


def run_job(job_id: str):
    started = time.monotonic()
    with LOCK:
        job = JOBS[job_id]
        if job["status"] == "CANCELLED":
            return
        job["status"] = "RUNNING"
        save_job(job)
    directory = ROOT / "jobs" / job_id
    try:
        image = read_image(input_path(job["fileId"]))
        if job["demo"]:
            _, all_masks = demo_geometry()
            masks = {n: all_masks[n] for n in job["organs"]}
            version = "synthetic-v1"
            for name, mask in masks.items():
                output = nib.Nifti1Image(mask.astype(np.uint8), image.affine)
                output.header.set_xyzt_units("mm")
                nib.save(output, directory / (name + ".nii.gz"))
        else:
            # Separate process keeps torch/model memory outside the API process and allows cancellation.
            command = [sys.executable, "-m", "worker.infer", str(input_path(job["fileId"])), str(directory),
                       "--device", os.environ.get("TOTALSEG_DEVICE", "cpu"), "--organs", *job["organs"]]
            if job["fast"]:
                command += ["--fast"]
            env = os.environ.copy()
            env["TOTALSEG_HOME_DIR"] = str(ROOT / "models")
            with open(directory / "inference.log", "w", encoding="utf-8") as log:
                with LOCK:
                    if job["status"] == "CANCELLED":
                        return
                    process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1], env=env, stdout=log, stderr=log)
                    PROCESSES[job_id] = process
                try:
                    code = process.wait(timeout=int(os.environ.get("INFERENCE_TIMEOUT_SECONDS", "1800")))
                except subprocess.TimeoutExpired:
                    cancel_job(job_id)
                    raise ValueError("模型推理超时")
            if code:
                raise ValueError("模型进程失败，请查看该任务的 inference.log；可能是权重下载或内存不足")
            masks = {}
            for name in job["organs"]:
                result = nib.load(directory / (name + ".nii.gz"))
                if result.shape != image.shape or not np.allclose(result.affine, image.affine, atol=1e-3):
                    raise ValueError("模型输出与原图坐标不一致，已停止统计")
                masks[name] = result.get_fdata() > .5
            import importlib.metadata
            version = importlib.metadata.version("TotalSegmentator")
        statistics, previews = summarize(image, masks, directory)
        result = {"model": job["model"], "modelVersion": version, "task": "total", "demo": job["demo"],
                  "statistics": statistics, "previews": previews, "masks": [n + ".nii.gz" for n in masks],
                  "inputSha256": job["inputSha256"], "fast": job["fast"], "elapsedSeconds": round(time.monotonic() - started, 2),
                  "warnings": ["合成几何演示，不代表模型推理效果"] if job["demo"] else ["研究用途；边界截断或空分割需人工核查，不能直接解释为器官异常"]}
        (directory / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        with LOCK:
            if job["status"] != "CANCELLED":
                job.update(status="SUCCEEDED", result=result)
            save_job(job)
    except Exception as exc:
        with LOCK:
            if job["status"] != "CANCELLED":
                job.update(status="FAILED", error=str(exc)[:500])
            save_job(job)
    finally:
        with LOCK:
            PROCESSES.pop(job_id, None)
