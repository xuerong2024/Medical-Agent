package local.medagent;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.*;

@Service
public class Knowledge {
    final Store store;
    final boolean vector;
    final String url,key,model;
    final HttpClient http=HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).connectTimeout(Duration.ofSeconds(10)).build();
    public Knowledge(Store store,@Value("${agent.vector-enabled}") boolean vector,@Value("${agent.embedding-url}") String url,
                     @Value("${agent.embedding-key}") String key,@Value("${agent.embedding-model}") String model) {
        this.store=store;this.vector=vector;this.url=url;this.key=key;this.model=model;
        if(vector) {
            if(url.isBlank())throw new IllegalStateException("向量模式需要 EMBEDDING_BASE_URL，且数据库须为 PostgreSQL + pgvector");
            store.db.execute("CREATE EXTENSION IF NOT EXISTS vector");
            store.db.execute("CREATE TABLE IF NOT EXISTS knowledge_vector (chunk_id VARCHAR(36) PRIMARY KEY, model VARCHAR(300), embedding vector)");
        }
        if(store.db.queryForObject("SELECT COUNT(*) FROM knowledge_chunk",Integer.class)==0) {
            add("TotalSegmentator 方法说明","https://github.com/wasserth/TotalSegmentator","TotalSegmentator 使用公开预训练模型进行 CT 解剖结构分割。肝脏 liver、脾脏 spleen 和左右肾 kidney 是本项目支持的器官。fast 模式采用较低分辨率，适合流程验证；比较结果时需要固定模型和参数。此条为项目整理的技术摘要，非临床指南。",false);
            add("体积计算与空间信息","https://nipy.org/nibabel/coordinate_systems.html","分割体积由掩膜体素数量乘以体素物理体积计算。使用 affine 空间变换矩阵的行列式取得体素体积，mm³ 除以 1000 得到 mL。需要确认影像空间单位与 mask 坐标一致。触及影像边界的器官可能显示不完整，不能把局部体积当作完整器官体积。",false);
            add("结果解释与适用边界","https://github.com/wasserth/TotalSegmentator","器官分割结果是模型估计，需要核对输入模态、扫描范围、图像方向、强度和输出质量。空掩膜不等于器官缺失，体积差异不自动构成疾病判断。本系统用于研究演示，不输出诊断结论。",false);
        }
    }
    public String mode(){return vector?"pgvector + "+model:"本地关键词检索（未启用向量）";}
    public List<Map<String,Object>> all(){return store.db.query("SELECT id,title,source,body FROM knowledge_chunk",(r,n)->Map.of("id",r.getString(1),"title",r.getString(2),"source",r.getString(3),"text",r.getString(4)));}
    public List<String> add(String title,String source,String text,boolean embed) {
        if(title.isBlank()||title.length()>300||source.length()>2000||text.isBlank()||text.length()>100000)throw new IllegalArgumentException("文档标题、来源或内容长度不合法");
        if(!source.isBlank()&&!source.startsWith("https://")&&!source.startsWith("http://"))throw new IllegalArgumentException("来源应为 http(s) 链接或留空");
        var ids=new ArrayList<String>();
        int size=model.equals("BAAI/bge-small-zh-v1.5")?400:800,step=model.equals("BAAI/bge-small-zh-v1.5")?330:650;
        for(int start=0;start<text.length();start+=step){
            String id=UUID.randomUUID().toString(),chunk=text.substring(start,Math.min(start+size,text.length()));
            String embedding=vector&&embed?embed(chunk):null;
            store.db.update("INSERT INTO knowledge_chunk(id,title,source,body) VALUES(?,?,?,?)",id,title,source,chunk);
            if(embedding!=null)store.db.update("INSERT INTO knowledge_vector(chunk_id,model,embedding) VALUES(?,?,CAST(? AS vector))",id,model,embedding);
            ids.add(id);
        }
        return ids;
    }
    public int reindex(){
        if(!vector)throw new IllegalArgumentException("请先配置 PostgreSQL、Embedding 并启用 VECTOR_ENABLED");
        int count=0;
        for(var chunk:all()) {
            String embedding=embed(chunk.get("text").toString());
            store.db.update("INSERT INTO knowledge_vector(chunk_id,model,embedding) VALUES(?,?,CAST(? AS vector)) ON CONFLICT(chunk_id) DO UPDATE SET model=EXCLUDED.model,embedding=EXCLUDED.embedding",chunk.get("id"),model,embedding);count++;
        }
        return count;
    }
    String embed(String input) {
        return embed(input,false);
    }
    String embed(String input,boolean query) {
        try {
            String endpoint=url.replaceAll("/$","");if(!endpoint.endsWith("/v1"))endpoint+="/v1";
            var body=new LinkedHashMap<String,Object>();body.put("model",model);body.put("input",input);
            if(model.equals("BAAI/bge-small-zh-v1.5"))body.put("input_type",query?"query":"document");
            var request=HttpRequest.newBuilder(URI.create(endpoint+"/embeddings")).timeout(Duration.ofSeconds(120)).header("Authorization","Bearer "+key).header("Content-Type","application/json")
                .POST(HttpRequest.BodyPublishers.ofString(store.encode(body))).build();
            var response=http.send(request,HttpResponse.BodyHandlers.ofString());
            if(response.statusCode()!=200)throw new IllegalStateException("Embedding API HTTP "+response.statusCode());
            var values=store.json.readTree(response.body()).path("data").get(0).path("embedding");
            if(!values.isArray()||values.isEmpty())throw new IllegalStateException("Embedding 返回为空");
            return values.toString();
        }catch(Exception e){throw new IllegalStateException("向量生成失败，请检查 Embedding 配置",e);}
    }
    public List<Map<String,Object>> search(String query) {
        if(query==null||query.isBlank())return List.of();
        if(vector) {
            String v=embed(query,true);
            return store.db.query("SELECT c.id,c.title,c.source,c.body,1-(v.embedding <=> CAST(? AS vector)) AS score FROM knowledge_chunk c JOIN knowledge_vector v ON c.id=v.chunk_id WHERE v.model=? AND vector_dims(v.embedding)=vector_dims(CAST(? AS vector)) ORDER BY v.embedding <=> CAST(? AS vector) LIMIT 4",
                (r,n)->Map.<String,Object>of("id",r.getString(1),"title",r.getString(2),"source",r.getString(3),"text",r.getString(4),"score",r.getDouble(5)),v,model,v,v).stream().filter(x->((Number)x.get("score")).doubleValue()>=.45).toList();
        }
        var terms=new HashSet<String>();String clean=query.toLowerCase().replaceAll("[^\\p{L}\\p{N}]", " ");
        for(String token:clean.split("\\s+")){
            if(token.length()>1)terms.add(token);
            if(token.matches(".*[\\p{IsHan}].*"))for(int i=0;i<token.length()-1;i++)terms.add(token.substring(i,i+2));
        }
        var hits=new ArrayList<Map<String,Object>>();
        for(var chunk:all()){
            String hay=(chunk.get("title")+" "+chunk.get("text")).toLowerCase();
            long score=terms.stream().filter(hay::contains).count();
            if(score>0){var hit=new LinkedHashMap<>(chunk);hit.put("score",score);hits.add(hit);}
        }
        hits.sort((a,b)->Long.compare(((Number)b.get("score")).longValue(),((Number)a.get("score")).longValue()));
        return hits.stream().limit(4).toList();
    }
}
