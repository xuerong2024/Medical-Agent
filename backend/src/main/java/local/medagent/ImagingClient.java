package local.medagent;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;

/** Minimal MCP Streamable HTTP client for our stateless, JSON-response server. */
@Component
public class ImagingClient {
    final HttpClient http = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).connectTimeout(Duration.ofSeconds(10)).build();
    final ObjectMapper json;
    final String base;
    final AtomicLong sequence = new AtomicLong();
    volatile boolean initialized;
    public ImagingClient(ObjectMapper json,@Value("${agent.worker-url}") String base) { this.json=json; this.base=base.replaceAll("/$",""); }
    public JsonNode request(String path,String method,byte[] body,String contentType) {
        try {
            if(path.equals("/mcp"))path="/mcp/";
            var builder=HttpRequest.newBuilder(URI.create(base+path)).timeout(Duration.ofSeconds(60));
            if(contentType!=null) builder.header("Content-Type",contentType);
            if(path.startsWith("/mcp")) builder.header("Accept","application/json, text/event-stream").header("MCP-Protocol-Version","2024-11-05");
            var response=http.send(builder.method(method,body==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofByteArray(body)).build(),HttpResponse.BodyHandlers.ofString());
            if(response.statusCode()>=300) throw new IllegalStateException("影像服务 HTTP "+response.statusCode()+": "+response.body().substring(0,Math.min(300,response.body().length())));
            return response.body().isBlank()?json.createObjectNode():json.readTree(response.body());
        } catch(IllegalStateException e) { throw e; } catch(Exception e) { throw new IllegalStateException("无法连接本地影像服务，请检查 worker 是否启动",e); }
    }
    private JsonNode rpc(String method,Map<String,Object> params,boolean notification) {
        try {
            var payload=new LinkedHashMap<String,Object>(); payload.put("jsonrpc","2.0");payload.put("method",method);payload.put("params",params);
            if(!notification) payload.put("id",sequence.incrementAndGet());
            var response=request("/mcp","POST",json.writeValueAsBytes(payload),"application/json");
            if(response.has("error")) throw new IllegalStateException(response.get("error").toString());
            if(!notification&&!response.has("result"))throw new IllegalStateException("MCP 返回缺少 result："+response.toString());
            return response.path("result");
        } catch(java.io.IOException e) { throw new IllegalStateException(e); }
    }
    private synchronized void initialize() {
        if(initialized)return;
        rpc("initialize",Map.of("protocolVersion","2024-11-05","capabilities",Map.of(),"clientInfo",Map.of("name","medical-agent-java","version","0.1.0")),false);
        rpc("notifications/initialized",Map.of(),true); initialized=true;
    }
    public JsonNode tool(String name,Map<String,Object> arguments) {
        initialize();
        var result=rpc("tools/call",Map.of("name",name,"arguments",arguments),false);
        if(result.path("isError").asBoolean()) throw new IllegalArgumentException(result.path("content").toString());
        try { return json.readTree(result.path("content").get(0).path("text").asText()); }
        catch(Exception e) { throw new IllegalStateException("MCP 工具返回格式不正确",e); }
    }
    public JsonNode tools() { initialize(); return rpc("tools/list",Map.of(),false); }
    public JsonNode health() { return request("/health","GET",null,null); }
    public byte[] artifact(String job,String name) {
        UUID.fromString(job);
        if(!name.matches("[a-z_]+\\.(png|nii\\.gz|json)"))throw new IllegalArgumentException("无效产物名称");
        try {
            var response=http.send(HttpRequest.newBuilder(URI.create(base+"/artifacts/"+job+"/"+name)).timeout(Duration.ofSeconds(60)).build(),HttpResponse.BodyHandlers.ofByteArray());
            if(response.statusCode()!=200)throw new IllegalArgumentException("产物不存在");
            return response.body();
        } catch(java.io.IOException|InterruptedException e){throw new IllegalStateException("产物读取失败",e);}
    }
}
