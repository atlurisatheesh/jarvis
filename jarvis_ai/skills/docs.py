"""Document skills: ingest your files into RAG, then answer from them."""
from .. import rag


def ingest_docs(folder: str) -> str:
    return rag.ingest(folder)


def ask_docs(question: str) -> str:
    context = rag.query(question)
    if not context:
        return "No documents ingested yet. Ask me to 'ingest' a folder first."
    # Returned as a tool result; the brain composes the spoken answer from it.
    return f"Relevant excerpts from your documents:\n{context}"


SKILLS = [
    ({"name": "ingest_docs",
      "description": "Index a folder of .txt/.md/.pdf files so questions can be answered from them.",
      "parameters": {"type": "object",
                     "properties": {"folder": {"type": "string"}}, "required": ["folder"]}}, ingest_docs),
    ({"name": "ask_docs",
      "description": "Answer a question using the user's own ingested documents (RAG).",
      "parameters": {"type": "object",
                     "properties": {"question": {"type": "string"}}, "required": ["question"]}}, ask_docs),
]
