package local.medagent;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import java.time.Instant;
import java.util.*;

@Component
public class Store {
    final JdbcTemplate db;
    final ObjectMapper json;
    public Store(JdbcTemplate db, ObjectMapper json) {
        this.db = db; this.json = json;
        db.execute("CREATE TABLE IF NOT EXISTS analysis_task (id VARCHAR(36) PRIMARY KEY, created_at VARCHAR(40), payload TEXT NOT NULL)");
        db.execute("CREATE TABLE IF NOT EXISTS task_event (task_id VARCHAR(36), seq INTEGER, payload TEXT NOT NULL, PRIMARY KEY(task_id,seq))");
        db.execute("CREATE TABLE IF NOT EXISTS knowledge_chunk (id VARCHAR(36) PRIMARY KEY, title VARCHAR(300), source VARCHAR(2000), body TEXT NOT NULL)");
        db.execute("CREATE TABLE IF NOT EXISTS chat_conversation (id VARCHAR(36) PRIMARY KEY, title VARCHAR(120), created_at VARCHAR(40), updated_at VARCHAR(40))");
        for (var task : list()) {
            if (Set.of("QUEUED","RUNNING","WAITING_TOOL").contains(task.get("status"))) {
                task.put("status", "FAILED"); task.put("error", "后端重启，任务中断；请重新提交"); save(task);
            }
        }
        // Preserve old task history as conversations, and attach followups to their original chat.
        for(var task:db.query("SELECT payload FROM analysis_task ORDER BY created_at",(r,n)->decode(r.getString(1)))) {
            if(task.containsKey("conversationId"))continue;
            String parent=Objects.toString(task.get("parentId"),"");String conversation="";
            if(!parent.isBlank())try{conversation=Objects.toString(get(parent).get("conversationId"),"");}catch(Exception ignored){}
            if(conversation.isBlank())conversation=createConversation(Objects.toString(task.get("prompt"),"历史会话"),task.get("createdAt").toString());
            task.put("conversationId",conversation);save(task);touch(conversation);
        }
    }
    String encode(Object object) { try { return json.writeValueAsString(object); } catch(Exception e) { throw new IllegalStateException(e); } }
    Map<String,Object> decode(String value) { try { return json.readValue(value, new TypeReference<LinkedHashMap<String,Object>>(){}); } catch(Exception e) { throw new IllegalStateException(e); } }
    public synchronized void create(Map<String,Object> task) {
        db.update("INSERT INTO analysis_task(id,created_at,payload) VALUES(?,?,?)",task.get("id"),task.get("createdAt"),encode(task));
    }
    public synchronized void save(Map<String,Object> task) { db.update("UPDATE analysis_task SET payload=? WHERE id=?",encode(task),task.get("id")); }
    public synchronized Map<String,Object> get(String id) {
        UUID.fromString(id);
        var rows = db.query("SELECT payload FROM analysis_task WHERE id=?",(r,n)->decode(r.getString(1)),id);
        if(rows.isEmpty()) throw new IllegalArgumentException("任务不存在");
        return rows.get(0);
    }
    public synchronized List<Map<String,Object>> list() { return db.query("SELECT payload FROM analysis_task ORDER BY created_at DESC LIMIT 100",(r,n)->decode(r.getString(1))); }
    public synchronized void patch(String id, Map<String,Object> fields) { var task=get(id); task.putAll(fields); save(task); }
    public synchronized void event(String id, String type, Object data) {
        Integer seq = db.queryForObject("SELECT COALESCE(MAX(seq),0)+1 FROM task_event WHERE task_id=?",Integer.class,id);
        db.update("INSERT INTO task_event(task_id,seq,payload) VALUES(?,?,?)",id,seq,encode(Map.of("seq",seq,"type",type,"data",data,"time",Instant.now().toString())));
    }
    public List<Map<String,Object>> events(String id,int after) { return db.query("SELECT payload FROM task_event WHERE task_id=? AND seq>? ORDER BY seq",(r,n)->decode(r.getString(1)),id,after); }
    public synchronized String createConversation(String title,String time){
        String id=UUID.randomUUID().toString();db.update("INSERT INTO chat_conversation(id,title,created_at,updated_at) VALUES(?,?,?,?)",id,title.substring(0,Math.min(50,title.length())),time,time);return id;
    }
    public synchronized void touch(String id){if(db.update("UPDATE chat_conversation SET updated_at=? WHERE id=?",Instant.now().toString(),id)==0)throw new IllegalArgumentException("会话不存在");}
    public List<Map<String,Object>> conversations(){return db.query("SELECT id,title,created_at,updated_at FROM chat_conversation ORDER BY updated_at DESC",(r,n)->Map.of("id",r.getString(1),"title",r.getString(2),"createdAt",r.getString(3),"updatedAt",r.getString(4)));}
    public List<Map<String,Object>> messages(String conversation){
        UUID.fromString(conversation);
        if(db.queryForObject("SELECT COUNT(*) FROM chat_conversation WHERE id=?",Integer.class,conversation)==0)throw new IllegalArgumentException("会话不存在");
        return db.query("SELECT payload FROM analysis_task ORDER BY created_at",(r,n)->decode(r.getString(1))).stream().filter(t->conversation.equals(t.get("conversationId"))).toList();
    }
    public void renameConversation(String id,String title){
        UUID.fromString(id);if(title.isBlank()||title.length()>100)throw new IllegalArgumentException("标题须为 1–100 字符");
        if(db.update("UPDATE chat_conversation SET title=? WHERE id=?",title,id)==0)throw new IllegalArgumentException("会话不存在");
    }
}
