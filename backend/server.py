from flask import Flask, request, jsonify
import os
import requests
import logging
from tenacity import retry, stop_after_attempt, wait_fixed
from neo4j import GraphDatabase
import traceback
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables or use default values
OPENAI_ENDPOINT = os.getenv("OPENAI_ENDPOINT", "https://ls-s-eus-paulohagan-openai.openai.azure.com/openai/deployments/gpt-4o-mini/chat/completions?api-version=2024-08-01-preview")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "58f022d5560f4b3c99834c9ff5b8655d")

# Neo4j Database Connection Details
NEO4J_URI="bolt://localhost:7687"
NEO4J_USER="neo4j"
NEO4J_PASSWORD="ML10051005"



@retry(stop=stop_after_attempt(5), wait=wait_fixed(2))
def send_request(prompt):
    return requests.post(
        OPENAI_ENDPOINT,
        headers={"Content-Type": "application/json", "api-key": OPENAI_API_KEY},
        json={
            "messages": [
                {"role": "system", "content": "You are a Neo4j Cypher expert."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 200,
            "temperature": 0.7,
            "top_p": 0.95
        },
        timeout=10
    )

def prompt_to_cypher(user_input):
    prompt = f"""
      Convert the following natural language query into a Cypher query that runs on a Neo4j database with the following schema:

      Nodes:
      - (:Email {{id, date_time, subject, content, relevant, analysis}})
      - (:Person {{id}})
      - (:Topic {{name}})

      Relationships:
      - (:Person)-[:SEND]->(:Email)
      - (:Person)-[:RECEIVE]->(:Email)
      - (:Person)-[:Cc]->(:Email)
      - (:Person)-[:Bcc]->(:Email)
      - (:Email)-[:RESPONSIVE]->(:Topic)

      Example queries:
      1. "Find all emails sent by Alice."
        Cypher: MATCH (p:Person {{id: 'Alice'}})-[:SEND]->(e:Email) RETURN e

      2. "Find all recipients of email ID 123."
        Cypher: MATCH (p:Person)-[:RECEIVE]->(e:Email {{id: '123'}}) RETURN p

      3. "Find all emails that are marked as relevant."
        Cypher: MATCH (e:Email) WHERE e.relevant = 'yes' RETURN e

      4. "How many responsive emails did jeff.dasovich@enron.com send?"
        Cypher: MATCH (sender:Person {{id: 'jeff.dasovich@enron.com'}})-[:SEND]->(email:Email)-[:RESPONSIVE]->(:Topic {{name:'Topic 303'}})
        RETURN COUNT(email) AS responsive_emails_sent;

      5. "How many responsive emails did steven.kean@enron.com receive?"
        Cypher: MATCH (recipient:Person {{id: 'steven.kean@enron.com'}})-[:RECEIVE]->(email:Email)-[:RESPONSIVE]->(:Topic {{name: 'Topic 303'}})
        RETURN count(email) AS responsive_email_count;

     6. "How many responsive emails did jeff.dasovich@enron.com send to christopher.calger@enron.com?"
        Cypher: MATCH (sender:Person {{id: 'jeff.dasovich@enron.com'}})-[:SEND]->(email:Email)-[:RESPONSIVE]->(:Topic {{name:'Topic 303'}})
        MATCH (recipient:Person {{id: 'christopher.calger@enron.com'}})-[:RECEIVE]->(email)
        RETURN count(email) AS responsive_email_count;

    7. "How many responsive emails were janel.guerrero@enron.com BCC-ed on?"
        Cypher: MATCH (bccRecipient:Person {{id: 'janel.guerrero@enron.com'}})-[:Bcc]->(email:Email)-[:RESPONSIVE]->(:Topic {{name: 'Topic 303'}})
        RETURN count(email) AS responsive_email_bcc_count;

      User Query: "{user_input}"

      Cypher Query:

      Notice:
      1. Only answer the cypher, do not add any words
      2. Always enclose string values in single quotes (`'`)
      3. Never truncate the output. The query must be returned in one complete response.
      """
    try:
        response = send_request(prompt)
        response.raise_for_status()
        generated_text = response.json()['choices'][0]['message']['content']
        cleaned_query = generated_text.strip("```cypher").strip("``` ").strip()
        logger.info("Generated Cypher query: %s", cleaned_query)
        print(cleaned_query)
        return cleaned_query
    except requests.exceptions.RequestException as e:
        logger.error("OpenAI request failed: %s", e)
        return None

# Neo4j connection class
class Neo4jDatabase:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def execute_cypher(self, cypher_query):
        with self.driver.session() as session:
            result = session.run(cypher_query)
            return [record.data() for record in result]

# Initialize Neo4j connection
db = Neo4jDatabase(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)

def process_query(cypher_query):
    # Execute Cypher Query in Neo4j
    results = db.execute_cypher(cypher_query)

    # Display results
    if results:
        print("🔍 Query Results:")
        for record in results:
            print(record)
        return record
    else:
        print("⚠ No results found.")
        logger.info( "⚠ No results found.")
        return None

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    if not data or 'user_input' not in data:
        return jsonify({"error": "Missing 'user_input' parameter"}), 400

    user_input = data['user_input']
    logger.info("Received user query: %s", user_input)

    cypher_query = prompt_to_cypher(user_input)
    if not cypher_query:
        return jsonify({"error": "Failed to generate Cypher query"}), 500

    try:
        results = process_query(cypher_query)
        return jsonify({
            "cypher_query": cypher_query,
            "results": results
        })
    except Exception as e:
        logger.error("Error processing Cypher query: %s",  traceback.format_exc())
        return jsonify({"error": "Failed to process query", "details": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
