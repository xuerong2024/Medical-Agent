package local.medagent;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
class ConversationTest {
    @Test void oldTasksMigrateAndFollowupsStayInSameConversation(){
        var db=new JdbcTemplate(new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=PostgreSQL;DB_CLOSE_DELAY=-1","sa",""));
        var json=new ObjectMapper();var old=new Store(db,json);
        String first=UUID.randomUUID().toString(),next=UUID.randomUUID().toString();
        old.create(new LinkedHashMap<>(Map.of("id",first,"prompt","分析影像","createdAt","2026-11-13T00:00:00Z","status","SUCCEEDED")));
        old.create(new LinkedHashMap<>(Map.of("id",next,"parentId",first,"prompt","解释体积","createdAt","2026-11-13T00:01:00Z","status","SUCCEEDED")));
        var upgraded=new Store(db,json);String id=upgraded.get(first).get("conversationId").toString();
        assertEquals(id,upgraded.get(next).get("conversationId"));assertEquals(2,upgraded.messages(id).size());assertEquals(1,upgraded.conversations().size());
        upgraded.renameConversation(id,"公开 CT 分析");assertEquals("公开 CT 分析",upgraded.conversations().get(0).get("title"));
        assertThrows(IllegalArgumentException.class,()->upgraded.messages(UUID.randomUUID().toString()));
        assertEquals(1,new Store(db,json).conversations().size());
    }
}
