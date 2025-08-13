import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

def classify_from_req_id(req_id: str) -> str:
    """
    Reads temp/<req_id>/questions.txt and asks Groq to classify the lane.
    Returns one of: "web", "file", "mixed", "external_data", or "other".
    """
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    q_path = os.path.join("temp", req_id, "questions.txt")
    if not os.path.exists(q_path):
        raise FileNotFoundError(f"questions.txt not found at {q_path}")

    with open(q_path, "r", encoding="utf-8") as f:
        question = f.read().strip()

    system_prompt = '''
You are a task classifier for an autonomous data analyst AI.

Your goal: Read the user query and decide which *one* of the following lanes it belongs to.

Lanes:
1. "web" → The task clearly involves scraping or extracting data from websites or web pages.
2. "file" → The task involves reading or analyzing uploaded files (CSV, Excel, JSON, PDF, images, etc.).
3. "mixed" → The task involves both website scraping and file processing in the same query.
4. "external_data" → The task involves querying external databases, APIs, or publicly available datasets without scraping or file uploads (e.g., SQL DB, Kaggle datasets, pre-hosted data portals).

Rules:
- If the query explicitly mentions a file format to be uploaded → "file".
- If the query explicitly mentions a URL or website to fetch data from → "web".
- If the query requires both → "mixed".
- If the query requires data from a dataset, database, or API without scraping or file uploads → "external_data".
- Never guess lane types not in the list.
- Do not include explanations — only output the JSON.

Output format:
{"lane": "<one of: web, file, mixed, external_data>"}
'''

    completion = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question}
        ],
        temperature=0,
        reasoning_effort="low",
        response_format={"type": "json_object"}
    )

    try:
        # prefer .message.content style access
        response_text = completion.choices[0].message.content
        parsed = json.loads(response_text)
        return parsed.get("lane", "other")
    except Exception as e:
        print("Classification parsing error:", e)
        # fallback heuristics if classification failed
        qlower = question.lower()
        if any(ext in qlower for ext in [".csv", ".xlsx", ".json", "s3://", "uploaded"]):
            return "file"
        if "http://" in qlower or "https://" in qlower or "scrape" in qlower:
            return "web"
        return "other"


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python splitter.py <req_id>")
        sys.exit(1)
    req_id = sys.argv[1]
    print(classify_from_req_id(req_id))
