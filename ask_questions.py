#!/usr/bin/env python3
"""
ask_questions.py

This script:
  1) Loads the vector store ID saved by ingest_policies.py
  2) Runs a File Search-powered Responses API call
  3) Prints the grounded answer
  4) Displays which files/snippets were used as sources
"""

import os
from dotenv import load_dotenv
from openai import OpenAI

MODEL = "gpt-4o-mini"
STORE_ID_FILE = "store_id.txt"


def print_search_citations(response):
    """
    Attempts to print which files/segments were used (when annotations are present).
    """
    try:
        for idx, item in enumerate(response.output):
            content = getattr(item, "content", None)
            if not content:
                continue
            for block in content:
                annotations = getattr(block, "annotations", None)
                if not annotations:
                    continue
                print(f"\n[Debug] Retrieved chunks for output[{idx}]:")
                for ann in annotations:
                    fname = getattr(ann, "filename", None)
                    score = getattr(ann, "score", None)
                    snippet = getattr(ann, "text", "")[:100]
                    print(f"- from: {fname} (score={score}) snippet={snippet!r}")
    except Exception as e:
        print(f"[Info] Couldn't extract annotations: {e}")


def main():
    # load_dotenv()
    # cert = os.path.join(os.path.dirname(__file__), '../Zscaler.cer')
    # os.environ["REQUESTS_CA_BUNDLE"] = cert
    # os.environ["SSL_CERT_FILE"] = cert

    client = OpenAI()

    # Load vector store ID
    if not os.path.exists(STORE_ID_FILE):
        raise SystemExit("Run ingest_policies.py first to create a vector store.")
    with open(STORE_ID_FILE) as f:
        store_id = f.read().strip()

    # Ask user question
    query = input("Enter your policy question: ")

    # Call Responses API with File Search tool
    response = client.responses.create(
        model=MODEL,
        input=query,
        tools=[{
            "type": "file_search",
            "vector_store_ids": [store_id],
        }],
    )

    # Print answer
    print("\n=== Grounded Answer ===\n")
    final_text = None
    for item in response.output:
        content = getattr(item, "content", None)
        if not content:
            continue
        for block in content:
            if getattr(block, "type", "") == "output_text":
                final_text = block.text
    print(final_text or "[No answer text found]")

    # Print sources (if available)
    print("\n=== Sources (retrieved chunks) ===")
    print_search_citations(response)


if __name__ == "__main__":
    main()
