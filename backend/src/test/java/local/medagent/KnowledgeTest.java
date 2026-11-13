package local.medagent;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(properties={"spring.datasource.url=jdbc:h2:mem:tests;MODE=PostgreSQL;DB_CLOSE_DELAY=-1","agent.api-key=","agent.vector-enabled=false"})
class KnowledgeTest {
    @Autowired Knowledge knowledge;
    @Autowired AgentService agent;
    @Test void unknownQueryDoesNotFabricateEvidence(){assertTrue(knowledge.search("zzzzunrelated82741").isEmpty());}
    @Test void relevantChineseQueryReturnsRealSources(){var hits=knowledge.search("肝脏体积计算");assertFalse(hits.isEmpty());assertTrue(hits.stream().allMatch(h->h.get("source").toString().startsWith("https://")));}
    @Test void disallowExecutableSource(){assertThrows(IllegalArgumentException.class,()->knowledge.add("test","javascript:alert(1)","abc",false));}
    @Test void rejectUnsupportedOrgan(){assertThrows(IllegalArgumentException.class,()->agent.submit(java.util.Map.of("prompt","test","kind","qa","organs",java.util.List.of("brain"))));}
}
