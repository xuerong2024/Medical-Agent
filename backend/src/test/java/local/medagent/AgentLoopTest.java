package local.medagent;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;

/** Protocol simulation exercises real Spring AI serialization/tool loop, not an online model evaluation. */
class AgentLoopTest {
    final ObjectMapper json=new ObjectMapper();
    Store store(){return new Store(new JdbcTemplate(new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=PostgreSQL;DB_CLOSE_DELAY=-1","sa","")),json);}
    Map<String,Object> await(Store store,String id) throws Exception {
        for(int i=0;i<200;i++){
            var task=store.get(id);if(Set.of("SUCCEEDED","FAILED","CANCELLED").contains(task.get("status")))return task;Thread.sleep(50);
        }
        throw new AssertionError("Agent timed out");
    }
    @Test void actualSpringAiLoopExecutesToolsAndUsesResults() throws Exception {
        Store s=store();Knowledge kb=new Knowledge(s,false,"","","");ImagingClient worker=mock(ImagingClient.class);
        String jobId=UUID.randomUUID().toString();
        when(worker.tool(eq("inspect_image"),anyMap())).thenReturn(json.readTree("{\"shape\":[32,32,32],\"spacingMm\":[2,2,2],\"synthetic\":true}"));
        when(worker.tool(eq("submit_segmentation"),anyMap())).thenReturn(json.readTree("{\"id\":\""+jobId+"\"}"));
        when(worker.tool(eq("get_job"),anyMap())).thenReturn(json.readTree("{\"status\":\"SUCCEEDED\",\"result\":{\"demo\":true,\"model\":\"synthetic\",\"statistics\":[{\"organ\":\"liver\",\"volumeMl\":1.25}],\"warnings\":[\"synthetic\"]}}"));
        var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);var rounds=new AtomicInteger();var requests=new ArrayList<String>();
        server.createContext("/v1/chat/completions",exchange->{
            requests.add(new String(exchange.getRequestBody().readAllBytes(),StandardCharsets.UTF_8));int round=rounds.getAndIncrement();
            String[] names={"inspect_image","segment_organs","search_knowledge"};String[] args={"{}","{\"organs\":[\"liver\"]}","{\"query\":\"肝脏体积\"}"};
            Map<String,Object> message=round<3?Map.of("role","assistant","tool_calls",List.of(Map.of("id","call"+round,"type","function","function",Map.of("name",names[round],"arguments",args[round])))):Map.of("role","assistant","content","已完成工具执行；这是合成测试结果。");
            byte[] response=json.writeValueAsBytes(Map.of("id","chat-test","object","chat.completion","created",1,"model","test-model","choices",List.of(Map.of("index",0,"message",message,"finish_reason",round<3?"tool_calls":"stop")),"usage",Map.of("prompt_tokens",10,"completion_tokens",5,"total_tokens",15)));
            exchange.getResponseHeaders().add("Content-Type","application/json");exchange.sendResponseHeaders(200,response.length);exchange.getResponseBody().write(response);exchange.close();
        });server.start();
        AgentService agent=new AgentService(s,worker,kb,"test-only-not-a-real-key","http://127.0.0.1:"+server.getAddress().getPort(),"test-model",30);
        try {
            var task=agent.submit(Map.of("kind","analysis","fileId",UUID.randomUUID().toString(),"prompt","分析肝脏","organs",List.of("liver"),"demo",true));
            var result=await(s,task.get("id").toString());assertEquals("SUCCEEDED",result.get("status"),result.toString());
            assertEquals(4,rounds.get());assertFalse(((List<?>)result.get("citations")).isEmpty());
            assertTrue(requests.get(0).contains("segment_organs"));assertTrue(requests.get(3).contains("1.25"));
            assertFalse(requests.stream().anyMatch(r->r.contains(jobId)));verify(worker,times(1)).tool(eq("submit_segmentation"),anyMap());
        } finally {agent.stop();server.stop(0);}
    }
    @Test void unregisteredToolFailsWithoutExecution() throws Exception {
        Store s=store();Knowledge kb=new Knowledge(s,false,"","","");ImagingClient worker=mock(ImagingClient.class);
        var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/v1/chat/completions",exchange->{
            exchange.getRequestBody().readAllBytes();byte[] response=json.writeValueAsBytes(Map.of("id","test","object","chat.completion","created",1,"model","test","choices",List.of(Map.of("index",0,"message",Map.of("role","assistant","tool_calls",List.of(Map.of("id","bad","type","function","function",Map.of("name","delete_everything","arguments","{}")))),"finish_reason","tool_calls"))));
            exchange.getResponseHeaders().add("Content-Type","application/json");exchange.sendResponseHeaders(200,response.length);exchange.getResponseBody().write(response);exchange.close();
        });server.start();
        AgentService agent=new AgentService(s,worker,kb,"test-only","http://127.0.0.1:"+server.getAddress().getPort(),"test",30);
        try {var t=agent.submit(Map.of("kind","qa","prompt","测试未知工具"));assertEquals("FAILED",await(s,t.get("id").toString()).get("status"));verifyNoInteractions(worker);}
        finally {agent.stop();server.stop(0);}
    }
}
