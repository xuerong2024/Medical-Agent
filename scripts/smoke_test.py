"""Run against locally started services. Creates only synthetic public-test artifacts."""
import json
import time
import urllib.request
import urllib.error
BASE="http://127.0.0.1:8080/api"
def call(path,data=None):
    if path=="/tasks" and data is not None:data={**data,"localOnly":True}
    request=urllib.request.Request(BASE+path,data=None if data is None else json.dumps(data).encode(),headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(request,timeout=70) as response:return json.load(response)
def wait(task):
    for _ in range(120):
        task=call("/tasks/"+task["id"])
        if task["status"] in ("SUCCEEDED","FAILED","CANCELLED"):return task
        time.sleep(.5)
    raise AssertionError("task timeout")
health=call("/health");assert health["worker"]["status"]=="ok"
assert len(call("/tools")["tools"])==4
file=call("/files/demo",{})
task=wait(call("/tasks",{"prompt":"分割肝脏和脾脏，计算体积并检索资料","kind":"analysis","fileId":file["fileId"],"demo":True,"organs":["liver","spleen"]}))
assert task["status"]=="SUCCEEDED",task
assert len(task["result"]["statistics"])==2
assert task["result"]["demo"] is True
assert task["citations"]
with urllib.request.urlopen(BASE+"/artifacts/"+task["jobId"]+"/axial.png") as r:assert r.read(8)==b"\x89PNG\r\n\x1a\n"
events=call("/tasks/"+task["id"]+"/events");assert any(e["type"]=="tool_completed" for e in events)
with urllib.request.urlopen(BASE+"/tasks/"+task["id"]+"/stream") as r:assert b"event:done" in r.read()
follow=wait(call("/tasks",{"prompt":"体积是怎样计算的？","kind":"qa","conversationId":task["conversationId"]}))
assert follow["status"]=="SUCCEEDED" and follow["jobId"]==task["jobId"],follow
assert follow["conversationId"]==task["conversationId"]
assert follow["kind"]=="followup" and follow["parentId"]==task["id"]
messages=call("/conversations/"+task["conversationId"])["messages"]
assert [m["id"] for m in messages]==[task["id"],follow["id"]]
qa=wait(call("/tasks",{"prompt":"zzzzunrelated82741","kind":"qa"}))
assert qa["status"]=="SUCCEEDED" and not qa["citations"]
bad=wait(call("/tasks",{"prompt":"分割","kind":"analysis","fileId":file["fileId"],"demo":False,"organs":["liver"]}))
assert bad["status"]=="FAILED",bad
print(json.dumps({"passed":True,"analysisTask":task["id"],"followupTask":follow["id"],"checks":["health","MCP discovery","segmentation","citations","preview","SSE","followup reuse","no evidence","mode isolation"]},ensure_ascii=False,indent=2))
