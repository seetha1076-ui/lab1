"""
Lab 1.1 - Call a Bedrock model with InvokeModel and a model-specific JSON body.
Model details are read from AWS Systems Manager (SSM) Parameter Store.

SSM parameter (String or SecureString) holds JSON, for example:

aws ssm put-parameter --name /aipc01/model-config --type String --value '{
  "modelId": "",
  "region": "us-east-1",
  "maxTokens": 512,
  "temperature": 0.5,
  "topP": 0.9,
  "systemPrompt": "You are a concise AWS tutor."
}'

Optional key "extraBody": a JSON object merged into the request body as-is,
for model-specific fields this script does not set itself.

Usage:
  python invoke_model_ssm.py "Explain RAG in two sentences"
  python invoke_model_ssm.py "Explain RAG" --param /aipc01/model-config --ssm-region us-east-1
"""

import argparse
import json
import sys

import boto3
from botocore.exceptions import ClientError

DEFAULT_PARAM = "/aipc01/model-config"
CROSS_REGION_PREFIXES = ("us.", "eu.", "apac.", "global.", "us-gov.", "jp.", "au.", "ca.")


# --------------------------------------------------------------------------
# 1. Read model details from SSM Parameter Store
# --------------------------------------------------------------------------
def load_model_config(param_name: str, ssm_region: str | None) -> dict:
    ssm = boto3.client("ssm", region_name=ssm_region)
    try:
        resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
    except ClientError as err:
        sys.exit(f"Could not read SSM parameter {param_name}: {err}")

    raw = resp["Parameter"]["Value"]
    try:
        config = json.loads(raw)
    except json.JSONDecodeError:
        # Plain string parameter: treat the whole value as the model ID.
        config = {"modelId": raw.strip()}

    if "modelId" not in config:
        sys.exit(f"SSM parameter {param_name} has no 'modelId' key.")

    config.setdefault("maxTokens", 512)
    config.setdefault("temperature", 0.5)
    config.setdefault("topP", 0.9)
    return config


def provider_of(model_id: str) -> str:
    """'us.amazon.nova-lite-v1:0' -> 'amazon-nova'; 'anthropic.claude-...' -> 'anthropic'."""
    base = model_id
    for prefix in CROSS_REGION_PREFIXES:
        if base.startswith(prefix):
            base = base[len(prefix):]
            break
    vendor = base.split(".", 1)[0]
    if vendor == "amazon":
        return "amazon-nova" if ".nova" in base else "amazon-titan"
    return vendor  # anthropic, meta, mistral, cohere, ...


# --------------------------------------------------------------------------
# 2. Build the model-specific JSON body


# --------------------------------------------------------------------------
def build_body(provider: str, prompt: str, cfg: dict) -> dict:
    system = cfg.get("systemPrompt")

    if provider == "amazon-nova":
        body = {
            "schemaVersion": "messages-v1",
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {
                "maxTokens": cfg["maxTokens"],
                "temperature": cfg["temperature"],
                "topP": cfg["topP"],
            },
        }
        if system:
            body["system"] = [{"text": system}]

    elif provider == "amazon-titan":
        text = f"{system}\n\n{prompt}" if system else prompt
        body = {
            "inputText": text,
            "textGenerationConfig": {
                "maxTokenCount": cfg["maxTokens"],
                "temperature": cfg["temperature"],
                "topP": cfg["topP"],
            },
        }

    elif provider == "anthropic":
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": cfg["maxTokens"],
            "temperature": cfg["temperature"],
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        }
        if system:
            body["system"] = system

    elif provider == "meta":
        sys_block = (
            f"<|start_header_id|>system<|end_header_id|>\n\n{system}<|eot_id|>" if system else ""
        )
        body = {
            "prompt": (
                "<|begin_of_text|>" + sys_block
                + f"<|start_header_id|>user<|end_header_id|>\n\n{prompt}<|eot_id|>"
                + "<|start_header_id|>assistant<|end_header_id|>\n\n"
            ),
            "max_gen_len": cfg["maxTokens"],
            "temperature": cfg["temperature"],
            "top_p": cfg["topP"],
        }

    elif provider == "mistral":
        body = {
            "prompt": f"<s>[INST] {prompt} [/INST]",
            "max_tokens": cfg["maxTokens"],
            "temperature": cfg["temperature"],
            "top_p": cfg["topP"],
        }

    else:
        sys.exit(f"No body template for provider '{provider}'. Use extraBody or add a template.")

    body.update(cfg.get("extraBody", {}))
    return body


# --------------------------------------------------------------------------
# 3. Parse the model-specific response
# --------------------------------------------------------------------------
def parse_response(provider: str, payload: dict) -> tuple[str, dict]:
    if provider == "amazon-nova":
        blocks = payload["output"]["message"]["content"]
        text = "".join(b["text"] for b in blocks if "text" in b)  # skips reasoningContent
        usage = payload.get("usage", {})
    elif provider == "amazon-titan":
        result = payload["results"][0]
        text = result["outputText"]
        usage = {"inputTokens": payload.get("inputTextTokenCount"),
                 "outputTokens": result.get("tokenCount")}
    elif provider == "anthropic":
        text = "".join(b["text"] for b in payload["content"] if b.get("type") == "text")
        usage = payload.get("usage", {})
    elif provider == "meta":
        text = payload["generation"]
        usage = {"inputTokens": payload.get("prompt_token_count"),
                 "outputTokens": payload.get("generation_token_count")}
    elif provider == "mistral":
        text = payload["outputs"][0]["text"]
        usage = {}
    else:
        text, usage = json.dumps(payload, indent=2), {}
    return text.strip(), usage


# --------------------------------------------------------------------------
# 4. Call InvokeModel
# --------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="InvokeModel with config from SSM")
    parser.add_argument("prompt", help="Prompt to send to the model")
    parser.add_argument("--param", default=DEFAULT_PARAM, help="SSM parameter name")
    parser.add_argument("--ssm-region", default=None, help="Region of the SSM parameter")
    parser.add_argument("--show-body", action="store_true", help="Print the request body")
    args = parser.parse_args()

    cfg = load_model_config(args.param, args.ssm_region)
    model_id = cfg["modelId"]
    provider = provider_of(model_id)
    body = build_body(provider, args.prompt, cfg)

    if args.show_body:
        print("Request body:\n" + json.dumps(body, indent=2) + "\n")

    bedrock = boto3.client("bedrock-runtime", region_name=cfg.get("region", args.ssm_region))
    try:
        resp = bedrock.invoke_model(
            modelId=model_id,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
    except ClientError as err:
        code = err.response["Error"]["Code"]
        msg = err.response["Error"]["Message"]
        if "INVALID_PAYMENT_INSTRUMENT" in msg:
            sys.exit("Marketplace subscription failed (common on AISPL accounts). "
                     "Use an Amazon Nova or Titan model ID in the SSM parameter.")
        sys.exit(f"InvokeModel failed: {code}: {msg}")

    payload = json.loads(resp["body"].read())
    text, usage = parse_response(provider, payload)

    print(f"Model: {model_id}  (provider: {provider})")
    print(f"Latency header: {resp['ResponseMetadata']['HTTPHeaders'].get('x-amzn-bedrock-invocation-latency', 'n/a')} ms")
    print(f"Tokens: in={usage.get('inputTokens', usage.get('input_tokens'))} "
          f"out={usage.get('outputTokens', usage.get('output_tokens'))}\n")
    print(text)


if __name__ == "__main__":
    main()