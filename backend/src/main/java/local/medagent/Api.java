package local.medagent;

import jakarta.annotation.PreDestroy;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;

@RestController
@RequestMapping("/api")
public class Api {
    final Store store;final AgentService agent;final ImagingClient imaging;final Knowledge knowledge;
    final ScheduledExecutorService streams=Executors.newScheduledThreadPool(2);
    public Api(Store s,AgentService a,ImagingClient i,Knowledge k){store=s;agent=a;imaging=i;knowledge=k;}
    @GetMapping("/health") public Map<String,Object> health(){
        var info=new LinkedHashMap<String,Object>();info.put("agentMode",agent.mode());info.put("llmConfigured",agent.chat!=null);info.put("retrievalMode",knowledge.mode());
        info.put("llmStatus",agent.connectionStatus);info.put("model",agent.model);info.put("vectorEnabled",knowledge.vector);
        try{info.put("worker",imaging.health());}catch(Exception e){info.put("worker",Map.of("status","unavailable","message",e.getMessage()));}
        return info;
    }
    @GetMapping("/tools") public Object tools(){return imaging.tools();}
    @PostMapping("/connection/test") public Object testConnection(){return agent.testConnection();}
    @GetMapping("/conversations") public Object conversations(){return store.conversations();}
    @GetMapping("/conversations/{id}") public Object conversation(@PathVariable String id){return Map.of("id",id,"messages",store.messages(id));}
    @PatchMapping("/conversations/{id}") public Object rename(@PathVariable String id,@RequestBody Map<String,String> data){store.renameConversation(id,data.getOrDefault("title",""));return Map.of("id",id);}
    @PostMapping("/files/demo") public Object demo(){return imaging.request("/files/demo","POST",null,null);}
    @PostMapping(value="/files",consumes=MediaType.MULTIPART_FORM_DATA_VALUE) public Object upload(@RequestParam MultipartFile file) throws Exception {
        if(file.getOriginalFilename()==null||!(file.getOriginalFilename().toLowerCase().endsWith(".nii.gz")||file.getOriginalFilename().toLowerCase().endsWith(".nii")))throw new IllegalArgumentException("仅支持 .nii 或 .nii.gz");
        String boundary="medagent"+UUID.randomUUID().toString().replace("-","");
        String extension=file.getOriginalFilename().toLowerCase().endsWith(".nii.gz")?".nii.gz":".nii";
        byte[] head=("--"+boundary+"\r\nContent-Disposition: form-data; name=\"file\"; filename=\"upload"+extension+"\"\r\nContent-Type: application/octet-stream\r\n\r\n").getBytes(StandardCharsets.UTF_8);
        var bytes=new java.io.ByteArrayOutputStream();bytes.write(head);file.getInputStream().transferTo(bytes);bytes.write(("\r\n--"+boundary+"--\r\n").getBytes(StandardCharsets.UTF_8));
        return imaging.request("/files","POST",bytes.toByteArray(),"multipart/form-data; boundary="+boundary);
    }
    @PostMapping("/tasks") public Object create(@RequestBody Map<String,Object> input){return agent.submit(input);}
    @GetMapping("/tasks") public Object tasks(){return store.list();}
    @GetMapping("/tasks/{id}") public Object task(@PathVariable String id){return store.get(id);}
    @PostMapping("/tasks/{id}/cancel") public Object cancel(@PathVariable String id){return agent.cancel(id);}
    @GetMapping("/tasks/{id}/events") public Object events(@PathVariable String id,@RequestParam(defaultValue="0") int after){store.get(id);return store.events(id,after);}
    @GetMapping(value="/tasks/{id}/stream",produces=MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter stream(@PathVariable String id,@RequestParam(defaultValue="0") int after,@RequestHeader(value="Last-Event-ID",required=false) String last) {
        store.get(id);var emitter=new SseEmitter(120000L);var cursor=new java.util.concurrent.atomic.AtomicInteger(after);
        if(last!=null)try{cursor.set(Math.max(after,Integer.parseInt(last)));}catch(NumberFormatException ignored){}
        var future=new java.util.concurrent.atomic.AtomicReference<ScheduledFuture<?>>();
        Runnable close=()->{var f=future.get();if(f!=null)f.cancel(false);};
        emitter.onCompletion(close);emitter.onTimeout(close);emitter.onError(e->close.run());
        future.set(streams.scheduleAtFixedRate(()->{
            try {
                for(var event:store.events(id,cursor.get())) {emitter.send(SseEmitter.event().id(event.get("seq").toString()).name("step").data(event));cursor.set(((Number)event.get("seq")).intValue());}
                var task=store.get(id);
                if(Set.of("SUCCEEDED","FAILED","CANCELLED").contains(task.get("status"))) {emitter.send(SseEmitter.event().name("done").data(task));emitter.complete();close.run();}
                else emitter.send(SseEmitter.event().comment("heartbeat"));
            }catch(Exception e){emitter.complete();close.run();}
        },100,800,TimeUnit.MILLISECONDS));
        return emitter;
    }
    @GetMapping("/tasks/{id}/report") public ResponseEntity<byte[]> report(@PathVariable String id){
        return ResponseEntity.ok().header("Content-Disposition","attachment; filename=report-"+UUID.fromString(id)+".json").contentType(MediaType.APPLICATION_JSON).body(store.encode(store.get(id)).getBytes(StandardCharsets.UTF_8));
    }
    @GetMapping("/artifacts/{job}/{name}") public ResponseEntity<byte[]> artifact(@PathVariable String job,@PathVariable String name){
        var type=name.endsWith(".png")?MediaType.IMAGE_PNG:MediaType.APPLICATION_OCTET_STREAM;
        return ResponseEntity.ok().contentType(type).body(imaging.artifact(job,name));
    }
    @GetMapping("/knowledge") public Object knowledge(){return Map.of("mode",knowledge.mode(),"chunks",knowledge.all());}
    @PostMapping("/knowledge") public Object add(@RequestBody Map<String,String> input){return Map.of("ids",knowledge.add(input.getOrDefault("title",""),input.getOrDefault("source",""),input.getOrDefault("text",""),true));}
    @GetMapping("/knowledge/search") public Object search(@RequestParam String query){return knowledge.search(query);}
    @PostMapping("/knowledge/reindex") public Object reindex(){return Map.of("indexed",knowledge.reindex());}
    @ExceptionHandler({IllegalArgumentException.class,IllegalStateException.class})
    public ResponseEntity<?> error(RuntimeException e){return ResponseEntity.badRequest().body(Map.of("error",Objects.toString(e.getMessage(),"请求失败")));}
    @PreDestroy void stop(){streams.shutdownNow();}
}
