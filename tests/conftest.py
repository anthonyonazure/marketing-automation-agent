import os

# Mocks + stub LLM
os.environ.setdefault("B2B_USE_MOCKS", "true")
os.environ.pop("ANTHROPIC_API_KEY", None)
