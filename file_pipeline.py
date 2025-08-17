import os
import pandas as pd
import subprocess
import json
import time
from groq import Groq
from dotenv import load_dotenv
import re
from io import open as io_open
import hashlib
from web_pipeline import fail_proof

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Models (you can tweak)
MAIN_MODEL = "openai/gpt-oss-120b"
CHECKER_MODEL = "openai/gpt-oss-20b"

# helpers
def replace_base64(text: str) -> str:
    """Truncate long base64-like strings in the given text to avoid context bloat."""
    if not text:
        return text
    base64_pattern = re.compile(r"[A-Za-z0-9+/=]{100,}")
    return base64_pattern.sub("[BASE64_REMOVED]", text)

def summarize_base64_in_text(text: str) -> str:
    """
    Replace base64 strings with a placeholder including size and hash,
    e.g. [BASE64_REMOVED size=52345 bytes sha256=abcd1234...]
    """
    if not text:
        return text

    def repl(match):
        b64_str = match.group(0)
        size = len(b64_str)
        # Compute SHA256 hash of the base64 string to uniquely identify it without leaking data
        sha256 = hashlib.sha256(b64_str.encode('utf-8')).hexdigest()[:8]
        return f"[BASE64_REMOVED size={size} bytes sha256={sha256}]"

    base64_pattern = re.compile(r"[A-Za-z0-9+/=]{100,}")
    return base64_pattern.sub(repl, text)

def probe_csv_structure(file_path):
    df = pd.read_csv(file_path, nrows=50)
    structure_info = {
        "file": os.path.basename(file_path),
        "columns": list(df.columns),
        "dtypes": df.dtypes.astype(str).to_dict(),
        "sample_rows": df.head(5).to_dict(orient="records")
    }
    return structure_info

def extract_python_code(text):
    if not text:
        return text
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:python)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()

def llm_call(messages, model):
    # Clean all messages before sending
    cleaned_messages = [{"role": m["role"], "content": replace_base64(m["content"])} for m in messages]
    resp = client.chat.completions.create(
        model=model,
        messages=cleaned_messages,
        temperature=0,
    )
    return resp.choices[0].message.content

def run_code_in_reqdir(code: str, req_dir: str, timeout: int = 120):
    temp_code_path = os.path.join(req_dir, f"step_code_{int(time.time()*1000)}.py")
    with io_open(temp_code_path, "w", encoding="utf-8") as f:
        f.write(code)
    try:
        proc = subprocess.run(
            ["python3", temp_code_path],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout or ""
        stderr = (e.stderr or "") + f"\nTIMEOUT: exceeded {timeout}s"
    except Exception as e:
        stdout = ""
        stderr = str(e)
    return stdout.strip(), stderr.strip()

def extract_json_from_text(text: str):
    if not text:
        return None
    start = None
    for i, ch in enumerate(text):
        if ch in ('{', '['):
            start = i
            break
    if start is None:
        return None
    for end in range(len(text), start, -1):
        candidate = text[start:end]
        try:
            return json.loads(candidate)
        except Exception:
            continue
    try:
        return json.loads(text)
    except Exception:
        return None

def file_pipeline(req_id: str):
    base_path = os.path.join("temp", req_id)
    question_path = os.path.join(base_path, "questions.txt")
    files_path = os.path.join(base_path, "files")

    if not os.path.exists(question_path):
        raise FileNotFoundError(f"questions.txt not found for req {req_id}")

    with io_open(question_path, "r", encoding="utf-8") as f:
        question = f.read().strip()

    if not os.path.isdir(files_path):
        raise FileNotFoundError(f"files folder not found for req {req_id}")

    structure_list = []
    for filename in sorted(os.listdir(files_path)):
        if filename.lower().endswith(".csv"):
            full = os.path.join(files_path, filename)
            try:
                structure_list.append(probe_csv_structure(full))
            except Exception as e:
                structure_list.append({"file": filename, "error": str(e)})

    structure_str = json.dumps(structure_list, indent=2)

    messages = [
        {"role": "system", "content": (
            "You are Adras, an autonomous data analyst. "
            "You will be given a user question and CSV structure metadata. "
            "Return only Python code (no explanations) that reads the CSV(s) from the 'files' folder "
            "and prints the final result (JSON) to stdout when done."
        )},
        {"role": "user", "content": f"Question:\n{question}\n\nCSV structure metadata:\n{structure_str}"}
    ]

    iteration = 0
    while True:
        iteration += 1
        raw_resp = llm_call(messages, MAIN_MODEL)
        code = extract_python_code(raw_resp)
        if not code:
            raise RuntimeError("LLM did not return any code. Raw response:\n" + str(raw_resp))

        stdout, stderr = run_code_in_reqdir(code, base_path, timeout=180)

        # Append assistant output (cleaned)
        messages.append({"role": "assistant", "content": replace_base64(raw_resp)})

        # Summarize base64 inside stdout for checker prompt
        summarized_stdout = summarize_base64_in_text(stdout)

        checker_messages = [
            {"role": "system", "content": "You are a binary task checker. Answer exactly 'yes' if the user's task is fully complete, else answer 'no'."},
            {"role": "user", "content": f"User question:\n{question}\n\nCode output:\n{summarized_stdout}\n\nCode errors:\n{stderr}\n\nIf the task is complete and the output contains the requested final result in JSON form, reply 'yes'. Otherwise reply 'no'."}
        ]
        decision = llm_call(checker_messages, CHECKER_MODEL)
        decision_text = decision.strip().lower()

        # Append feedback (cleaned)
        feedback = f"Output:\n{stdout}\nErrors:\n{stderr}"
        messages.append({"role": "user", "content": replace_base64(feedback)})

        if decision_text.startswith("y"):
            json_result = extract_json_from_text(stdout)
            if json_result is not None:
                return json_result
            return {"stdout": stdout, "stderr": stderr}

        if iteration >= 10:
            json_result = extract_json_from_text(stdout)
            if json_result is not None:
                return json_result
            return json.loads(fail_proof(stdout, question))

