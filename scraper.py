from groq import Groq
import os
import json
import subprocess
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GROQ_API_KEY")
client = Groq(api_key=api_key)

system_prompt = """
You are a web scraping specialist that extracts minimal table metadata from web pages.

Your task:
1. Take a URL and write Python code to identify the first table
2. Extract only essential metadata (NO actual data)
3. Use pandas.read_html() for table detection
4. Return minimal JSON format for table identification

Required output format:
{
  "url": "the_original_url",
  "tables": [
    {
      "table_index": 0,
      "columns": ["col1", "col2", ...],
      "num_rows": number_of_rows,
      "num_cols": number_of_columns
    }
  ]
}

Instructions:
- Use only standard Python libraries (pandas, requests, json)
- Extract ONLY metadata: table_index, columns, num_rows, num_cols
- DO NOT store actual row data or timestamps
- PROCESS ONLY THE FIRST TABLE (use tables[0] if exists)
- Handle errors gracefully
- Return only Python code, no explanations
"""
def ask_llm(messages):
    response = client.chat.completions.create(
        messages=messages,
        model="llama-3.3-70b-versatile",
        temperature=0,
    )
    return response.choices[0].message.content

def extract_python_code(text):
    text = text.strip()
    if text.startswith("```python"):
        text = text[9:]
        if text.endswith("```"):
            text = text[:-3]
    elif text.startswith("```"):
        text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()

def run_code(code):
    try:
        result = subprocess.run(
            ["python3", "-c", code],
            capture_output=True,
            text=True,
            timeout=30  # Shorter timeout for scraping
        )
        return result.stdout, result.stderr
    except Exception as e:
        return "", str(e)

def scrape(url):
    scraping_task = f"""
Extract minimal table metadata from this URL: {url}

Write Python code to:
1. Fetch the webpage using pandas.read_html()
2. Identify the FIRST table only (use tables[0] if exists)
3. Extract ONLY: table_index, columns, num_rows, num_cols
4. Format as minimal JSON structure
5. Print the final JSON result

Remember to:
- Handle cases where no tables are found
- DO NOT store actual row data, timestamps, or headings
- Extract only essential metadata for table identification
- PROCESS ONLY THE FIRST TABLE for efficiency
"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": scraping_task}
    ]
    max_iterations = 5 
    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        print(f"\n=== Iteration {iteration} ===")
        raw_code = ask_llm(messages)
        code = extract_python_code(raw_code)
        print(f"Generated scraping code:\n{code}")
        stdout, stderr = run_code(code)
        if checker(stdout):
            print("Table metadata extracted successfully.")
            json_data = json.loads(stdout)
            print(f"Metadata:\n{json.dumps(json_data, indent=2)}")
            return json_data
        else:
            messages.append({"role": "assistant", "content": code})
            messages.append({"role": "user", "content": f"Error: {stderr.strip()}"})
    return {"error": "Failed to extract table metadata after multiple attempts."}

def checker(stdout):
    # check if the output contains valid json
    try:
        json_data = json.loads(stdout)
        if isinstance(json_data, dict):
            return True
    except json.JSONDecodeError:
        pass
    return False

