import json
import os
from groq import Groq
from dotenv import load_dotenv
from web_pipeline import ask_llm
from web_pipeline import extract_python_code
from web_pipeline import run_code
from web_pipeline import replace_base64, fail_proof
import ast

load_dotenv()
api_key = os.getenv("GROQ_API_KEY")
client = Groq(api_key=api_key)

system_prompt = """
You are Adras, an autonomous AI data analyst.

You must:
    •	Solve complex natural language queries about data analysis.
    •	If needed, fetch or query data from the external source provided in the question.
    •	Use only standard Python libraries (pandas, requests, matplotlib, seaborn, duckdb, etc.).
    •	Write Python code to complete the task step by step. At each step, you will be given the original question and any previous code+output.
    •   Focus on generating fast and accurate python code.
    •	If a specific format (e.g. JSON array, base64 plot) is requested, format output accordingly.
    •	Return only the Python code, with no explanation or markdown formatting.
    •	When working with large datasets, never load the entire dataset into memory. Only load the necessary columns or rows.
    •	When a task includes specific instructions for visualizations (e.g., "use a dotted red line", "label axes", "keep image size under 100kB"), follow them **exactly**. Do not ignore stylistic or formatting requests, especially for plots.
"""

def checker_llm(question, summarized_stdout, stderr):
    response = client.chat.completions.create(
        messages=[
            {"role": "system", "content": "You are a binary task checker. Answer exactly 'yes' if the code output successfully matches the expected output even if the base64 is truncated, else answer 'no'."},
            {"role": "user", "content": f"User question:\n{question}\n\nCode output:\n{summarized_stdout}\n\nCode errors:\n{stderr}\n\nIf the task is complete and the output contains the requested final result in JSON form (base64 will be truncated), reply 'yes'. Otherwise reply 'no'."}
        ],
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        temperature=0,
    )
    return response.choices[0].message.content

def extract_json(text: str) -> str:
	if not text:
		return text

	start_idx: int | None = None
	stack: list[str] = []

	in_string = False
	quote_char = ''  # either ' or " when inside a string
	escape = False   # only relevant when inside a string

	for i, ch in enumerate(text):
		# If we haven't started capturing, look for the first opening brace/bracket.
		if start_idx is None:
			if ch == '{' or ch == '[':
				start_idx = i
				stack.append(ch)
			# ignore everything until we see the first '{' or '['
			continue

		# We have started capturing inside a potential JSON fragment.
		if in_string:
			if escape:
				# current char is escaped; consume and reset
				escape = False
			else:
				if ch == '\\':
					escape = True
				elif ch == quote_char:
					in_string = False
			continue

		# Not in a string within the captured fragment
		if ch == '"' or ch == "'":
			in_string = True
			quote_char = ch
			continue

		if ch == '{' or ch == '[':
			stack.append(ch)
			continue

		if ch == '}' or ch == ']':
			if not stack:
				# Unbalanced close; return best-effort slice
				return text[start_idx:i + 1]
			open_ch = stack.pop()
			if (open_ch == '{' and ch != '}') or (open_ch == '[' and ch != ']'):
				# Mismatched pair; cannot reliably extract – return original text
				return text
			if not stack:
				# Completed the outermost object/array
				return text[start_idx:i + 1]

		# otherwise, keep scanning

	# Reached end without closing the outermost structure – return original
	return text

def clean_json(stdout):
    import re
    if not isinstance(stdout, str):
        return stdout

    s = stdout

    # Unwrap numpy float wrappers like np.float64(4.764...) -> 4.764...
    s = re.sub(
        r'\b(?:np|numpy)\.float64\(\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*\)',
        r'\1',
        s,
    )
    return s

def external_pipeline(req_id):
    question = open(f"temp/{req_id}/questions.txt").read()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question}
    ]
    max_iterations = 5
    clean_stdout = ""
    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        print(f"\n=== Iteration {iteration} ===")
        raw_code = ask_llm(messages)
        code = extract_python_code(raw_code)
        print(f"Generated code:\n{code}")
        stdout, stderr = run_code(code)
        clean_stdout = clean_json(extract_json(stdout))
        print(f"Code output:\n{clean_stdout}\nErrors:\n{stderr}")
        if (checker_llm(question, replace_base64(clean_stdout), stderr) == "yes"):
            print("Task complete. Returning final output.")
            return ast.literal_eval(clean_stdout)
        else:
            messages.append({"role": "assistant", "content": code})
            messages.append({"role": "user", "content": "Output = " + replace_base64(clean_stdout) + "\nErrors = " + stderr})
            continue
    print("Max iterations reached. Task failed.")
    return json.loads(fail_proof(clean_stdout, question))

