"""Custom SageMaker inference handler for snowflake-arctic-embed-m-v1.5.

Does CLS-token pooling + L2 normalization server-side, returning compact
sentence embeddings (batch, 768) instead of raw token-level tensors
(batch, tokens, 768).  This reduces response size from ~67 MB to ~140 KB
for a typical batch of 32 texts.
"""

import json

import torch
import torch.nn.functional as f
from transformers import AutoModel, AutoTokenizer


def model_fn(model_dir):
    """Load model with no pooling layer (we do CLS pooling ourselves)."""
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModel.from_pretrained(model_dir, add_pooling_layer=False)
    model.eval()
    return {"model": model, "tokenizer": tokenizer}


def input_fn(request_body, content_type):
    """Deserialize JSON input."""
    if content_type == "application/json":
        data = json.loads(request_body)
        inputs = data.get("inputs", data)
        if isinstance(inputs, str):
            inputs = [inputs]
        return inputs
    raise ValueError(f"Unsupported content type: {content_type}")


def predict_fn(inputs, model_dict):
    """Embed texts using CLS-token pooling + L2 normalization.

    Returns a plain Python list so the default output_fn can
    JSON-serialize it without double-encoding.
    """
    if not inputs:
        return []

    model = model_dict["model"]
    tokenizer = model_dict["tokenizer"]

    encoded = tokenizer(
        inputs,
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    )

    with torch.no_grad():
        outputs = model(**encoded)

    # CLS token pooling (first token of last hidden state)
    cls_embeddings = outputs.last_hidden_state[:, 0]
    # L2 normalize to match local ONNX model output
    normalized = f.normalize(cls_embeddings, p=2, dim=1)
    return normalized.tolist()
