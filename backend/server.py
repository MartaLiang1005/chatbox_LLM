from flask import Flask, request, jsonify
import os
import requests
import logging
import re
import json
from flask_cors import CORS
from tenacity import retry, stop_after_attempt, wait_fixed
from neo4j import GraphDatabase
import spacy

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration (load your own endpoint and keys)
endpoint = os.getenv("OPENAI_ENDPOINT", "https://ls-s-eus-paulohagan-openai.openai.azure.com/openai/deployments/gpt-4o-mini/chat/completions?api-version=2024-08-01-preview")
api_key = os.getenv("OPENAI_API_KEY", "58f022d5560f4b3c99834c9ff5b8655d")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "ML10051005")

# Load NLP model for entity extraction
ner = spacy.load("en_core_web_trf")

# Retryable OpenAI request
def send_request(payload):
    @retry(stop=stop_after_attempt(5), wait=wait_fixed(2))
    def do_post(p):
        return requests.post(
            endpoint,
            headers={"Content-Type": "application/json", "api-key": api_key},
            json={
            "messages": [
                {"role": "system", "content": "You are a Neo4j Cypher expert."},
                {"role": "user", "content": p}
            ],
            "max_tokens": 200,
            "temperature": 0,
            "top_p": 0.95
        },
            timeout=10
        )
    return do_post(payload)

REFRAME_QUESTION_PROMPT = """
You are an intelligent query refiner for a Neo4j database. Your task is to take a user's natural language question, analyze its meaning, and reframe it into a more precise query. You should clarify ambiguous terms and confirm with the user that the reframed question correctly represents their intent.

### Neo4j Database Schema:
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

### Instructions:
Given a natural language question, perform the following steps:

1. **Analyze the user's question:**
    - Identify vague or ambiguous terms (e.g., "important," "related," "best," "most relevant").
    - Break down the question into measurable database attributes (e.g., number of emails sent, received, Bcc'd).
    - Consider how the question aligns with Neo4j's data structure (e.g., nodes, relationships, and properties).

2. **Reframe the question with a clear definition:**
    - Most important!:If in the chat history, assistant or user has identified email address for persons, please use email instead of person's name.
    - Rewrite the question to remove ambiguity.
    - Ensure that it can be directly translated into a Cypher query.
    - Keep it concise and specific to the database schema.

3. **Confirm with the user:**
    - Explain why you redefined the question in a concise, logical explanation.
    - Ask the user for confirmation or clarification if the intent is still unclear.

4. **Determine whether to terminate the clarification process:**
    - If the user's message indicates they no longer want to clarify, reframe, or refine the question (e.g., "stop," "this is good enough," "no need to clarify further"), then set `"termination_status": true`.
    - Otherwise, set `"termination_status": false`.

### Response Format:
Return a JSON object with the following fields:

- "reframed_question": The clearer, more structured version of the user's question.
- "explanation": A brief analysis of why the question was reframed this way.
- "confirmation_message": A follow-up prompt to the user to ensure accuracy or request more details.
- "termination_status": Boolean indicating whether to stop further clarification (true = stop, false = continue).

Return only valid JSON format, without any additional explanatory text or code block markup

### Example 1:

#### User's Input:
"Who is the most important person around topic 303?"

#### Generated JSON Response:
```json
{{
  "reframed_question": "Who sent the most emails about topic 303?",
  "explanation": "The term 'most important' is ambiguous. We assume it refers to the number of emails sent. Thus, the most important person is the one who has sent the most emails related to topic 303.",
  "confirmation_message": "Is this what you meant by 'most important,' or do you have another definition in mind?",
  "termination_status": false
}}"

### Example 2:

#### User's Input:
"How many emails did Paul send to Dan?"

Most important!:If in the chat history, assistant or user has identified email address for persons, please use email instead of person's name.

#### Generated JSON Response:
```json
{{
  "reframed_question": "How many emails did Paul send to Dan?",
  "explanation": "The original question is already clear and specific, asking for a count of emails sent by Paul to Dan. This can be directly translated into a Cypher query to retrieve the relevant data.",
  "confirmation_message": "Does this accurately capture your question, or would you like to adjust any details?",
  "termination_status": true
}}"

Most important!:If in the chat history, assistant or user has identified email address for persons, please use email instead of person's name.

"""

message_list = [
    {"role": "developer", "content": REFRAME_QUESTION_PROMPT}
]   # message_list is a list of dictionaries that keeps all dialogue history between user and assistant


def clarify_user_question(message_list):
    # API Request Headers
    headers = {
        "Content-Type": "application/json",
        "api-key": api_key
    }

    # API request payload
    payload = {
        "model": "gpt-4",
        "messages": message_list,
        "max_tokens": 300,
        "temperature": 0.3
    }

    try:
        # Send request to OpenAI API
        response = requests.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()  # Raise an exception if there's an error
        response_json = response.json()
        # Extract the generated response
        if "choices" in response_json and len(response_json["choices"]) > 0:
            gpt_response_text = response_json["choices"][0]["message"]["content"]

            # Clean possible Markdown formatting in GPT response
            clean_json_str = re.sub(r"```json\n|\n```", "", gpt_response_text.strip())

            # Parse the response as JSON
            json_data = json.loads(clean_json_str)

            # Extract required fields
            reframed_question = json_data.get("reframed_question", "N/A")
            explanation = json_data.get("explanation", "N/A")
            confirmation_message = json_data.get("confirmation_message", "N/A")
            termination_status = json_data.get("termination_status", "N/A")

            # Return structured response
            return {
                "reframed_question": reframed_question,
                "explanation": explanation,
                "confirmation_message": confirmation_message,
                "termination_status": termination_status
            }
        else:
            return {"error": "No response from OpenAI API"}

    except requests.exceptions.RequestException as e:
        print(f"API Error: {e}")
        return {"error": "API request failed"}

    except json.JSONDecodeError as e:
        print(f"JSON Decode Error: {e}")
        return {"error": "Failed to parse JSON response"}
    

cy_prompt = f"""
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

    8. "How many responsive emails were sent after "1997-09-10T08:00:00?"
        Cypher: MATCH (sender:Person)-[:SEND]->(e:Email)-[:RESPONSIVE]->(:Topic {{name: 'Topic 303'}})
        WHERE e.date_time > datetime("1997-09-10T08:00:00")
        RETURN count(e) AS responsive_emails_after_date;

      Notice:
      1. Always produce a valid Cypher query that includes a complete RETURN clause.
      2. If you do not have enough information to produce a valid Cypher query, output exactly this text instead:
       "Please clarify. Question is too ambiguous".
      3. Only answer the cypher, do not add any words.
      4. Always enclose string values in single quotes (`'`)
      5. Never truncate the output. The query must be returned in one complete response.
      6.- All Person nodes use their **email address** as the `id`.
        - If a user's question includes a person's **name**, and not their email, you can generate a Cypher such as:
        `WHERE toLower(p.id) CONTAINS "<person name>"`
        This ensures the system can perform **fuzzy matching** on email IDs.
      7. Always use the correct relationship direction: (:Person)-[:RELATION]->(:Email). Do not reverse it.

      Cypher Query:
      """

# Generate Cypher query via OpenAI
@retry(stop=stop_after_attempt(5), wait=wait_fixed(2))
def prompt_to_cypher(user_input=None,prompt=None):
  gen_prompt = f"""
      {cy_prompt}
      User Query: "{user_input}"

      """
  if prompt==None:
      prompt=gen_prompt
  else:
      prompt=prompt
  try:
      response = send_request(prompt)
      response.raise_for_status()
      generated_text = response.json()['choices'][0]['message']['content']
      # Remove markdown markers using replace instead of strip:
      cleaned_query = generated_text.replace("```cypher", "").replace("```", "").strip()
      print(cleaned_query)
      return cleaned_query
  except requests.exceptions.RequestException as e:
      print(f"An error occurred: {e}")
      if hasattr(e, 'response') and e.response:
          print(f"Status code: {e.response.status_code}")
          print(f"Response body: {e.response.text}")
# Neo4j driver wrapper
class Neo4jDatabase:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
    def close(self):
        self.driver.close()
    def execute_cypher(self, query):
        with self.driver.session() as session:
            return [record.data() for record in session.run(query)]


def execute_cypher(query):
    """
    Execute a Cypher query using the Neo4j driver.
    """
    # If `db` is a driver instance
    try:
        with db.session() as session:
            return [record.data() for record in session.run(query)]
    except AttributeError:
        # Fallback for wrapper with `driver`
        with db.driver.session() as session:
            return [record.data() for record in session.run(query)]
        
# Initialize Neo4j
db = Neo4jDatabase(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)

# Execute Cypher with syntax-fix retry
def error_handling_query(cypher_query,prompt=None):
    tried_debug = False #this makes sure we only go through syntax fixing once
    if prompt==None:
        prompt= cy_prompt
    while True:
        try:
            # Execute Cypher Query in Neo4j
            results = db.execute_cypher(cypher_query)

            # Display results
            if results:
                print("🔍 Query Results:")
                for record in results:
                    print(record)
                return results
            else:
                print("⚠ No results found.")
                return []
            return
        #adding an exept clause to deal with syntax errors:
        except Exception as e:
            error_str = str(e)

            if "SyntaxError" in error_str or "invalid input" in error_str:
                # Try debugging once
                if not tried_debug:
                    tried_debug = True
                    print("⛔ Syntax error encountered, attempting to fix with LLM...")

                    # Build a "debug" prompt that can be passed to the same LLM:
                    debug_prompt = f"""
                    Original Prompt:{prompt}
                    The Cypher query below caused a syntax error in Neo4j.
                    Original query: {cypher_query}

                    Error message: {error_str}

                    Please correct the query.
                    Rules:
                      1. Only provide the corrected query, no extra explanation.
                      2. Enclose string values in single quotes.
                      3. The query must be complete (no truncation).
                    """

                    # Reuse prompt_to_cypher to fix the query
                    debugged_query = prompt_to_cypher(prompt=debug_prompt)

                    # If the LLM returned something, retry
                    if debugged_query:
                        cypher_query = debugged_query
                        continue  # Retry the while loop with new query
                    else:
                        print("No corrected query was returned by the LLM. Stopping.")
                        print("Original error:", error_str)
                        return
                else:
                    # Already tried once
                    print("⛔ Query still failing after one debug attempt.")
                    print("Error:", error_str)
                    return
            else:
                # Some non-syntax error, just print and stop
                print("⛔ A non-syntax error occurred:")
                print(error_str)
                return []
            
def check_person_existence(person_id):
    # name_search_prompt = f"""
    # Given a user's input containing a person's name (e.g., "jeff dasovich", "Dasovich, Jeff", "Jeff Dasovich?"), generate a Cypher query that finds all :Person nodes whose `id` field (email address) contains the normalized version of the name.

    # Schema:
    # - (:Person {{id}})

    # Instructions:
    # 1. Normalize the input name by:
    # - Removing extra characters like commas, question marks, or punctuation.
    # - Reordering names if needed (e.g., "Dasovich, Jeff" → "jeff dasovich").
    # - Converting the name to lowercase.
    # - Joining first and last name with a dot `.` (e.g., "jeff dasovich" → "jeff.dasovich").

    # 2. Use `toLower(p.id) CONTAINS '<normalized_name>'` in the query for fuzzy match.
    # 3. Always produce a valid Cypher query that includes a complete RETURN clause.
    # 4. Always enclose string values in single quotes (`'`)
    # 5. Never truncate the output. The query must be returned in one complete response.
    # 6.- All Person nodes use their **email address** as the `id`.
    # - If a user's question includes a person's **name**, and not their email, you can generate a Cypher such as:
    # `WHERE toLower(p.id) CONTAINS "<person name>"`
    # This ensures the system can perform **fuzzy matching** on email IDs.

    # ---

    # ### Example

    # Input: Jeff Dasovich?
    # Normalized: jeff.dasovich

    # Cypher:
    # MATCH (p:Person)
    # WHERE toLower(p.id) CONTAINS 'jeff.dasovich'
    # RETURN p.id AS person_id

    # ---

    # Input: {person_id}

    # Cypher:
    # """
    person_id=person_id.split(" ")
    if len(person_id)>=2:
        person_id=".".join(person_id)
    else:
        person_id=person_id[0]

    check_query = f"""
    MATCH (p:Person)
    WHERE toLower(p.id) CONTAINS toLower('{person_id}')
    RETURN p.id AS person_id
    """
    # check_query=prompt_to_cypher(prompt=name_search_prompt)
    results = error_handling_query(check_query)
    match_count = len(results)
    print(match_count)
    matched_ids = [r['person_id'] for r in results]
    return (match_count, matched_ids)

def process_query(cypher_query):
    """
    Execute a Cypher query and display the results,
    with pre-check for person ID existence and uniqueness.
    """
    return error_handling_query(cypher_query)

# Format results into natural language via OpenAI
def format_result_naturally(user_input, cypher_query, cypher_result):
    prompt = f"""
You are an assistant that turns Cypher query results into clear and natural language answers.

User Query: "{user_input}"
Cypher Query: {cypher_query}
Result: {cypher_result}

Give a single, concise sentence that answers the user question naturally,only using the data from User Query,Cypher Query and result.
"""
    try:
        response = send_request(prompt)
        response.raise_for_status()
        generated_text = response.json()['choices'][0]['message']['content'].strip()
        logger.info("Generated natural language output: %s", generated_text)
        return generated_text
    except Exception as e:
        logger.error("LLM formatting failed: %s", e)
        return "Sorry, I couldn't generate a natural language response."

def demo_check(reframed_question):
    """
    Validate PERSON entities in the reframed question and return structured results:
      - {'error': msg} if a name isn't found
      - {'ambiguous_names': [...]} if multiple matches
      - {'cleaned_question': reframed_question} otherwise
    """
    doc = ner(reframed_question)
    person_entities = [ent.text for ent in doc.ents if ent.label_ == "PERSON"]
    ambiguous = []

    for name in person_entities:
        parts = name.split()
        normalized = ".".join(parts).lower() if len(parts) > 1 else parts[0].lower()
        query = f"""
        MATCH (p:Person)
        WHERE toLower(p.id) CONTAINS '{normalized}'
        RETURN p.id AS person_id
        """
        results = execute_cypher(query)
        count = len(results)
        if count == 0:
            return {'error': f"Person '{name}' not found in database."}
        if count > 1:
            ambiguous.append({'name': name, 'options': [r['person_id'] for r in results]})

    if ambiguous:
        print("multiple matches:", ambiguous)
        return {'ambiguous_names': ambiguous}
    return {'cleaned_question': reframed_question}

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json() or {}
    user_input = data.get('user_input')
    if not user_input:
        return jsonify({'error': "Missing 'user_input' parameter"}), 400

    logger.info("User Query: %s", user_input)

    # 1. Clarification
    history = [
        {'role': 'developer', 'content': REFRAME_QUESTION_PROMPT},
        {'role': 'user', 'content': user_input}
    ]
    clar = clarify_user_question(history)
    if 'error' in clar:
        return jsonify({'error': clar['error']}), 500
    if clar['reframed_question'].startswith("Please clarify."):
        return jsonify({
            'reframed_question': clar['reframed_question'],
            'explanation': clar['explanation'],
            'confirmation_message': clar['confirmation_message'],
            'termination_status': False
        }), 200

    reframed = clar['reframed_question']

    # 2. Person-entity validation
    check = demo_check(reframed)
    if 'error' in check:
        return jsonify({'error': check['error']}), 400
    if 'ambiguous_names' in check:
        return jsonify({
            'clarify_person': True,
            'message': "Multiple persons matched; please choose one.",
            'ambiguous_names': check['ambiguous_names'],
            'termination_status': False
        }), 200

    cleaned = check['cleaned_question']

    # 3. Cypher generation
    cypher = prompt_to_cypher(cleaned)
    if not cypher:
        return jsonify({'error': "Failed to generate Cypher query."}), 500
    if cypher.startswith("Please clarify."):
        return jsonify({'natural_response': cypher}), 200

    # 4. Execute
    results = error_handling_query(cypher)
    if not results:
        return jsonify({'cypher_query': cypher, 'results': [], 'natural_response': "No matching data found."}), 200

    # 5. Natural language
    natural = format_result_naturally(user_input, cypher, results)
    return jsonify({'cypher_query': cypher, 'results': results, 'natural_response': natural})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
