
from datetime import datetime, timezone
from falkordb import FalkorDB

# Connect to local FalkorDB
db = FalkorDB(host="localhost", port=6379)
graph = db.select_graph("fflake")

ts = datetime.now(timezone.utc).isoformat()

# Create a synthetic company's capability graph
graph.query("""
CREATE
  (s:UntrustedSource {id:'web-1', name:'Untrusted Webpage'}),
  (b:Tool {id:'browser-1', name:'Browser'}),
  (a:Agent {id:'agent-1', name:'Support Agent'}),
  (t:Tool {id:'crm-tool-1', name:'CRM Write Tool'}),
  (c:Credential {id:'cred-1', name:'Privileged CRM Credential'}),
  (crm:System {id:'crm-1', name:'CRM'}),
  (d:DataStore {id:'data-1', name:'Customer Records'}),

  (s)-[:INFLUENCED_BY {created_at:$ts}]->(b),
  (b)-[:INFLUENCED_BY {created_at:$ts}]->(a),
  (a)-[:CAN_INVOKE {created_at:$ts}]->(t),
  (t)-[:HOLDS {created_at:$ts}]->(c),
  (c)-[:GRANTS_ACCESS_TO {created_at:$ts}]->(crm),
  (crm)-[:CAN_WRITE {created_at:$ts}]->(d)
""", {"ts": ts})

# Find directed paths from untrusted sources to sensitive data
result = graph.query("""
MATCH p = (s:UntrustedSource)-[*1..8]->(d:DataStore)
RETURN p
""")

print("FFlake graph initialized.")
print("Capability paths found:", len(result.result_set))

for row in result.result_set:
    print(row[0])

print("Investigation complete.")
